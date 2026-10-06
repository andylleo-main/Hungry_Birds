import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/printer.dart';
import '../state/merchant_state.dart';
import '../state/orders_state.dart';

class OrdersTab extends StatelessWidget {
  const OrdersTab({super.key});

  @override
  Widget build(BuildContext context) {
    final ordersState = context.watch<OrdersState>();
    final merchant = context.watch<MerchantState>();
    final isOpen = merchant.vendor?.isOpen ?? false;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Orders'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Row(
              children: [
                Text(
                  isOpen ? 'Open' : 'Closed',
                  style: TextStyle(
                    color: isOpen ? AppTheme.success : AppTheme.textSecondary,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
                Switch(
                  value: isOpen,
                  activeThumbColor: AppTheme.success,
                  onChanged: (value) => context.read<MerchantState>().setOpen(value),
                ),
              ],
            ),
          ),
        ],
      ),
      body: _buildBody(context, ordersState),
    );
  }

  Widget _buildBody(BuildContext context, OrdersState state) {
    if (state.loading) {
      return const Center(child: CircularProgressIndicator(color: AppTheme.primaryRed));
    }
    if (state.error != null) {
      return ErrorRetry(message: state.error.toString(), onRetry: state.load);
    }

    final active = state.activeOrders;
    final past = state.pastOrders;

    if (active.isEmpty && past.isEmpty) {
      return const EmptyState(
        icon: Icons.receipt_long_outlined,
        title: 'No orders yet',
        message: 'New orders from students land here the moment they are placed.',
      );
    }

    return RefreshIndicator(
      color: AppTheme.primaryRed,
      onRefresh: state.load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          if (active.isNotEmpty) ...[
            const _SectionTitle('Live orders'),
            for (final order in active) ...[
              _OrderCard(order: order, live: true),
              const SizedBox(height: 12),
            ],
          ],
          if (past.isNotEmpty) ...[
            const SizedBox(height: 8),
            const _SectionTitle('Past orders'),
            for (final order in past) ...[
              _OrderCard(order: order, live: false),
              const SizedBox(height: 12),
            ],
          ],
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;

  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10, top: 4),
        child: Text(text, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
      );
}

class _OrderCard extends StatefulWidget {
  final Order order;
  final bool live;

  const _OrderCard({required this.order, required this.live});

  @override
  State<_OrderCard> createState() => _OrderCardState();
}

/// What the assign sheet came back with: a rider, the merchant, or nobody.
class _Assignment {
  const _Assignment({this.riderId, this.selfDelivery = false});

  final String? riderId;
  final bool selfDelivery;
}

class _OrderCardState extends State<_OrderCard> {
  bool _busy = false;

  /// Separate from _busy, which blanks the whole action row for a status change.
  /// Printing must not hide the buttons: a merchant whose printer is off should
  /// still be able to tap "Start preparing" while the attempt times out.
  bool _printing = false;

  void _say(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  /// Cancelling refunds a paid order, so it asks first.
  ///
  /// Rejecting at `placed` needs no confirmation - the stall has not committed
  /// to anything yet. By `accepted` the customer has been told their food is
  /// being made, so a mis-tap here is worth one extra step.
  Future<void> _confirmCancel() async {
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Cancel this order?'),
        content: const Text(
          'The customer gets their money back and is told you could not make '
          "it. This cannot be undone.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep it'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Cancel order'),
          ),
        ],
      ),
    );
    if (go == true && mounted) await _move(OrderStatus.cancelled);
  }

  /// Accepts, after asking how long it will take.
  ///
  /// The field is pre-filled with what the stall's own menu times worked out, so
  /// the common case is a glance and a tap. The merchant is the one looking at
  /// the actual kitchen, though, so their number wins over the menu's.
  ///
  /// Skipping is a real option rather than a hidden one: a stall that has filled
  /// in no prep times has nothing to suggest, and being made to invent a number
  /// under a queue of waiting students is how a wrong one gets typed.
  Future<void> _acceptWithTime() async {
    final order = widget.order;
    final controller = TextEditingController(text: order.prepMinutes?.toString() ?? '');

    final minutes = await showDialog<String?>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('How long will this take?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: controller,
              keyboardType: TextInputType.number,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Cooking time',
                suffixText: 'min',
              ),
            ),
            const SizedBox(height: 10),
            Text(
              order.isDelivery
                  ? 'Cooking only. We add 15 minutes for the ride.'
                  : 'The customer sees this as their wait.',
              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, null),
            child: const Text('Skip'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('Accept'),
          ),
        ],
      ),
    );
    controller.dispose();

    // Null is the dialog being dismissed or skipped, which still accepts - the
    // order is the thing that matters and a stall should never be stuck behind
    // this question. An empty string is the same.
    if (!mounted) return;
    await _move(OrderStatus.accepted, prepMinutes: int.tryParse(minutes ?? ''));
  }

  Future<void> _move(OrderStatus status, {int? prepMinutes}) async {
    setState(() => _busy = true);
    try {
      await context
          .read<OrdersState>()
          .updateStatus(widget.order, status, prepMinutes: prepMinutes);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = widget.order;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _StatusChip(status: order.status),
                const SizedBox(width: 8),
                // The number this stall shouts across the counter. Biggest thing
                // in the header on purpose: it is what a cook matches a bag to.
                // Absent on an order placed before tokens existed, so it is
                // drawn conditionally rather than with a placeholder.
                if (order.tokenNumber != null)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: AppTheme.primaryRed,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      '#${order.tokenNumber}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                const Spacer(),
                Text(
                  DateFormat('d MMM, h:mm a').format(order.createdAt.toLocal()),
                  style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
                // Printing lives here, in the header, because it is not a step
                // in the order's life - it is something a stall does to an
                // order, at any point, as often as they need.
                //
                // It used to sit inside the "accepted" branch of _actions,
                // which made it reachable only between tapping Accept and
                // tapping Start preparing. The natural flow is to do those two
                // things together, so in practice the button was gone before
                // anybody looked for it - and a jammed or lost ticket could
                // never be printed again, which the comment on _print claimed
                // was the whole reason printing is a separate tap.
                //
                // Past orders get it too: "print me that receipt again" is a
                // thing customers ask for after the fact.
                _PrintButton(order: order, onPrint: _print, busy: _printing),
              ],
            ),
            // The long number, for when a customer rings up about this order.
            // Quiet, because nobody reads it during service.
            if (order.orderNumber.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  order.orderNumber,
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 11,
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
              ),
            const SizedBox(height: 12),
            for (final item in order.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    Text('${item.quantity}x ', style: const TextStyle(fontWeight: FontWeight.w800)),
                    Expanded(child: Text(item.nameSnapshot)),
                    Text('₹${(item.priceSnapshot * item.quantity).toStringAsFixed(0)}'),
                  ],
                ),
              ),
            const SizedBox(height: 8),
            // Where this order is going. A delivery whose destination is not on
            // the card is an order the stall cannot actually fulfil, so this sits
            // above the note rather than beside the total.
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: (order.isDelivery ? AppTheme.primaryRed : AppTheme.textSecondary)
                    .withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(
                    order.isDelivery ? Icons.delivery_dining : Icons.restaurant,
                    size: 18,
                    color: order.isDelivery ? AppTheme.primaryRed : AppTheme.textSecondary,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      order.isDelivery
                          ? 'Deliver to ${order.deliveryLocationLabel ?? 'an unnamed place'}'
                          : 'Dine in - collecting at the counter',
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
            ),
            if (order.note != null && order.note!.isNotEmpty) ...[
              const SizedBox(height: 10),
              // Loud on purpose. This used to be 13px regular text on a 10%
              // amber wash with no border and no icon, which made it quieter
              // than the destination banner directly above it - so the one
              // thing on the card written by a person, and the one thing that
              // changes what goes in the bag, read as the least important.
              Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  color: AppTheme.warning.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                  border: const Border(
                    left: BorderSide(color: AppTheme.warning, width: 4),
                  ),
                ),
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.sticky_note_2, size: 16, color: AppTheme.warning),
                        const SizedBox(width: 6),
                        Text(
                          'NOTE FROM THE CUSTOMER',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.6,
                            color: AppTheme.warning.withValues(alpha: 0.95),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      order.note!,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        height: 1.3,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Divider(height: 1),
            ),
            // Used to say "paid online" unconditionally, with a comment that a
            // stall asking for cash as well would be charging twice. That was
            // true while every order was prepaid; pay on delivery is the design
            // being reversed, so the card has to show which of the two this is
            // rather than assert either.
            _PaymentLine(order: order),
            // Only when no rider is carrying it, which is the same question the
            // server asks. Not the selfDelivery flag: an order can go out with
            // nobody assigned, and gating on the flag hid the buttons on
            // exactly the orders where the stall is the only person who can
            // collect. A rider's order is collected for in the rider app, and
            // two people able to mark the same cash collected is how an order
            // gets marked paid by whoever is not holding the money.
            if (widget.live &&
                order.isAwaitingCollection &&
                order.riderId == null &&
                order.status == OrderStatus.outForDelivery) ...[
              const SizedBox(height: 10),
              _CollectActions(order: order),
            ],
            if (order.readyBy != null) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.schedule, size: 16, color: AppTheme.textSecondary),
                  const SizedBox(width: 8),
                  Text(
                    // What the customer was told, so the stall is looking at the
                    // same promise rather than guessing what was said on their
                    // behalf.
                    'Told ${DateFormat('h:mm a').format(order.readyBy!.toLocal())}'
                    '${order.isDelivery ? ' at the door' : ''}',
                    style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                  ),
                ],
              ),
            ],
            if (order.customerPhone != null) ...[
              const SizedBox(height: 10),
              _CustomerContact(name: order.customerName, phone: order.customerPhone!),
            ],
            if (widget.live && order.isDelivery) ...[
              const SizedBox(height: 10),
              _courierRow(order),
            ],
            // The customer has this too. It is here so the stall can read it
            // back to somebody whose phone has died at the gate - without that,
            // a lost code means an order nobody can close.
            if (order.isDelivery && order.deliveryCode != null) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Icon(Icons.pin_outlined, size: 18, color: AppTheme.textSecondary),
                  const SizedBox(width: 8),
                  const Text(
                    'Handover code',
                    style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                  ),
                  const Spacer(),
                  SelectableText(
                    order.deliveryCode!,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 3,
                    ),
                  ),
                ],
              ),
            ],
            if (widget.live) ...[
              const SizedBox(height: 12),
              _actions(order),
            ],
          ],
        ),
      ),
    );
  }

  /// Who is carrying this delivery, and the button to change that.
  Widget _courierRow(Order order) {
    final String who;
    if (order.selfDelivery) {
      who = "You're taking this one";
    } else if (order.riderName != null) {
      who = 'With ${order.riderName}';
    } else {
      who = 'Nobody assigned yet';
    }

    return Row(
      children: [
        Icon(
          order.hasCourier ? Icons.person : Icons.person_outline,
          size: 18,
          color: order.hasCourier ? AppTheme.success : AppTheme.warning,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            who,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
          ),
        ),
        TextButton(
          onPressed: _busy ? null : () => _assign(order),
          child: Text(order.hasCourier ? 'Change' : 'Assign'),
        ),
      ],
    );
  }

  /// Picks who takes this delivery out.
  ///
  /// The rider list is fetched when the sheet opens rather than held in state:
  /// it is small, it changes rarely, and a stale list here would mean offering a
  /// rider who was switched off since the queue was last loaded.
  Future<void> _assign(Order order) async {
    final api = context.read<ApiClient>();
    List<Rider> riders;
    try {
      riders = await api.myRiders();
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
      return;
    } catch (_) {
      if (mounted) _say("Couldn't load your riders. Check your connection.");
      return;
    }
    if (!mounted) return;

    final active = riders.where((r) => r.isActive).toList();

    final choice = await showModalBottomSheet<_Assignment>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Text(
                'Who is taking this out?',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.storefront),
              title: const Text("I'll take it myself"),
              selected: order.selfDelivery,
              onTap: () => Navigator.pop(context, const _Assignment(selfDelivery: true)),
            ),
            for (final r in active)
              ListTile(
                leading: const Icon(Icons.pedal_bike),
                title: Text(r.displayName),
                subtitle: Text(r.phone),
                selected: order.riderId == r.id,
                onTap: () => Navigator.pop(context, _Assignment(riderId: r.id)),
              ),
            if (active.isEmpty)
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 8, 16, 8),
                child: Text(
                  'No active riders. Add one on the Riders tab, or take this '
                  'delivery yourself.',
                  style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                ),
              ),
            if (order.hasCourier)
              ListTile(
                leading: const Icon(Icons.person_off_outlined),
                title: const Text('Nobody for now'),
                onTap: () => Navigator.pop(context, const _Assignment()),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;

    setState(() => _busy = true);
    try {
      await api.assignOrder(
        order.id,
        riderId: choice.riderId,
        selfDelivery: choice.selfDelivery,
      );
      // The queue already updates itself from the socket broadcast the assign
      // triggers, so there is nothing to reload here.
    } on ApiException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't assign that. Check your connection.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Sends the ticket to the counter printer.
  ///
  /// Kept off the accept action deliberately: accepting is the moment the stall
  /// commits to cooking, and a printer that is out of paper or out of range must
  /// not be able to fail that. So accepting always succeeds and printing is a
  /// separate tap, which also means a jammed ticket can simply be printed again.
  Future<void> _print(Order order) async {
    final printer = context.read<PrinterService>();
    final stallName = context.read<MerchantState>().vendor?.stallName ?? 'Hungry Birds';

    if (!printer.hasPrinter) {
      _say('No printer set up yet. Stall → Ticket printer.');
      return;
    }

    setState(() => _printing = true);
    try {
      await printer.printOrder(order, stallName: stallName);
    } on PrinterException catch (e) {
      if (mounted) _say(e.message);
    } catch (_) {
      if (mounted) _say("Couldn't print that ticket.");
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  Widget _actions(Order order) {
    if (_busy) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(6),
          child: SizedBox(
            height: 20,
            width: 20,
            child: CircularProgressIndicator(color: AppTheme.primaryRed, strokeWidth: 2.5),
          ),
        ),
      );
    }

    return switch (order.status) {
      OrderStatus.placed => Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => _move(OrderStatus.rejected),
                child: const Text('Reject'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: ElevatedButton(
                onPressed: _acceptWithTime,
                child: const Text('Accept'),
              ),
            ),
          ],
        ),
      // Cancel sits beside "start preparing" because the customer can no longer
      // cancel for themselves, and accepted -> cancelled is the last point where
      // anybody can stop an order. Without it, a student who ordered at the
      // wrong counter has no way out at all and the stall has no way to give it
      // to them. Cancelling refunds, same as rejecting.
      OrderStatus.accepted => Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _confirmCancel,
                child: const Text('Cancel'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              flex: 2,
              child: ElevatedButton(
                onPressed: () => _move(OrderStatus.preparing),
                child: const Text('Start preparing'),
              ),
            ),
          ],
        ),
      OrderStatus.preparing => SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: () => _move(OrderStatus.ready),
            child: Text(order.isDelivery ? 'Mark ready to go out' : 'Mark ready for pickup'),
          ),
        ),
      // A delivery the merchant is taking themselves is theirs to mark out and
      // then delivered. One assigned to a rider is marked from the rider's app,
      // so the stall is told rather than asked.
      OrderStatus.ready => order.isDelivery
          ? (order.selfDelivery
              ? SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () => _move(OrderStatus.outForDelivery),
                    child: const Text('Heading out with it'),
                  ),
                )
              : order.riderId != null
                  ? _Waiting(text: '${order.riderName ?? 'Your rider'} collects it from you')
                  : const _Waiting(text: 'Assign a rider, or take it yourself'))
          : SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => _move(OrderStatus.completed),
                child: const Text('Mark completed'),
              ),
            ),
      OrderStatus.outForDelivery => order.selfDelivery
          ? SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => _move(OrderStatus.completed),
                child: const Text('Delivered'),
              ),
            )
          : _Waiting(text: '${order.riderName ?? 'Your rider'} is on the way'),
      _ => const SizedBox.shrink(),
    };
  }
}

/// Print this order's ticket. Available at every status, including past orders.
///
/// Quiet on purpose: a small icon in the header rather than a button competing
/// with Accept and Start preparing, because during service the decisions matter
/// more than the paper. It is always *there*, though, which is the point - the
/// previous version appeared for one status only.
class _PrintButton extends StatelessWidget {
  const _PrintButton({required this.order, required this.onPrint, required this.busy});

  final Order order;
  final Future<void> Function(Order) onPrint;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    // Shown even with no printer set up, rather than hidden: _print answers
    // with where to set one up, which is more use than a button that silently
    // is not there on a phone whose owner is looking for it.
    return IconButton(
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
      onPressed: busy ? null : () => onPrint(order),
      icon: busy
          ? const SizedBox(
              height: 16,
              width: 16,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            )
          : const Icon(Icons.print_outlined, size: 20, color: AppTheme.textSecondary),
      tooltip: 'Print ticket',
    );
  }
}

/// A line of text where a button would be, for a step that is somebody else's
/// to take. Better than a disabled button, which reads as something the merchant
/// ought to be able to press.
class _Waiting extends StatelessWidget {
  const _Waiting({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AppTheme.textSecondary.withValues(alpha: 0.07),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            const Icon(Icons.hourglass_empty, size: 16, color: AppTheme.textSecondary),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                text,
                style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary),
              ),
            ),
          ],
        ),
      );
}

class _StatusChip extends StatelessWidget {
  final OrderStatus status;

  const _StatusChip({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      OrderStatus.completed || OrderStatus.ready || OrderStatus.accepted => AppTheme.success,
      OrderStatus.outForDelivery => AppTheme.success,
      OrderStatus.placed || OrderStatus.preparing => AppTheme.warning,
      // Never reaches a stall's queue - an unpaid order is filtered out server
      // side - but the enum is matched exhaustively on purpose, so the next
      // status added shows up here as a compile error rather than at runtime.
      OrderStatus.awaitingPayment => AppTheme.textSecondary,
      OrderStatus.rejected => AppTheme.primaryRed,
      OrderStatus.cancelled => AppTheme.textSecondary,
      // A status from a newer server. Left deliberately exhaustive rather than
      // given a wildcard: the analyzer then flags every switch like this one the
      // next time a status is added, which is the whole reason the enum has an
      // unknown member instead of throwing while decoding.
      OrderStatus.unknown => AppTheme.textSecondary,
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        status.label,
        style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12),
      ),
    );
  }
}

/// Customer name + phone with a one-tap call button. COD pickup means the
/// stall regularly needs to ring the customer when an order is ready.
class _CustomerContact extends StatelessWidget {
  const _CustomerContact({required this.name, required this.phone});

  final String? name;
  final String phone;

  Future<void> _call(BuildContext context) async {
    final uri = Uri(scheme: 'tel', path: phone);
    if (!await launchUrl(uri)) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not start a call. Number: $phone')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.background,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.person_outline, size: 18, color: AppTheme.textSecondary),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name?.isNotEmpty == true ? name! : 'Customer',
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                ),
                Text(
                  '+91 ${formatPhoneForDisplay(phone)}',
                  style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
              ],
            ),
          ),
          TextButton.icon(
            onPressed: () => _call(context),
            icon: const Icon(Icons.call, size: 16),
            label: const Text('Call'),
          ),
        ],
      ),
    );
  }
}


/// What the stall is owed, and whether anybody has it yet.
///
/// Three states, and the loud one is deliberate: an order the rider still has to
/// collect for is the one a stall needs to notice, because it is the one where
/// they have cooked food that is not yet paid for.
class _PaymentLine extends StatelessWidget {
  const _PaymentLine({required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    final amount = '₹${order.totalAmount.toStringAsFixed(0)}';

    if (order.isAwaitingCollection) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AppTheme.warning.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(8),
          border: const Border(left: BorderSide(color: AppTheme.warning, width: 4)),
        ),
        child: Row(
          children: [
            const Icon(Icons.payments_outlined, size: 18),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '$amount to collect on delivery',
                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
              ),
            ),
          ],
        ),
      );
    }

    final collected = switch (order.collectedVia) {
      'cash' => 'collected in cash',
      'upi' => 'collected by UPI',
      _ => 'paid online',
    };

    return Row(
      children: [
        Icon(
          order.isPaid ? Icons.check_circle_outline : Icons.info_outline,
          size: 18,
          color: order.isPaid ? AppTheme.success : AppTheme.textSecondary,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            order.isPaid ? '$amount $collected' : amount,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
      ],
    );
  }
}


/// Cash or a QR, for the owner who is delivering the order themselves.
///
/// The rider app has had both since pay on delivery shipped. This is the same
/// pair for the person with no rider to send - which, for a one-person stall,
/// is every delivery they take.
class _CollectActions extends StatefulWidget {
  const _CollectActions({required this.order});

  final Order order;

  @override
  State<_CollectActions> createState() => _CollectActionsState();
}

class _CollectActionsState extends State<_CollectActions> {
  bool _busy = false;

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _cash() => _run(() async {
        // Read before the dialog, not after: the confirmation is an async gap,
        // and reaching back through the context once it closes is the lint's
        // point rather than a formality.
        final orders = context.read<OrdersState>();
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: const Text('Taken the cash?'),
            // Marking it collected is what lets the order be closed, so it is
            // worth one tap of confirmation rather than being a button that
            // settles the money by accident.
            content: Text(
              'This records \u20b9${widget.order.totalAmount.toStringAsFixed(0)} '
              'as collected in cash.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('Not yet'),
              ),
              ElevatedButton(
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('Yes, got it'),
              ),
            ],
          ),
        );
        if (confirmed != true) return;
        await orders.collectCash(widget.order);
      });

  Future<void> _qr() => _run(() async {
        final orders = context.read<OrdersState>();
        final qr = await orders.upiQr(widget.order);
        if (!mounted) return;
        await showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          // Not dismissible by dragging: the phone is being held out to
          // somebody else, and a stray swipe closing the code mid-scan is the
          // one interaction this screen cannot afford.
          isDismissible: false,
          enableDrag: false,
          builder: (_) => StallUpiQrSheet(orderId: widget.order.id, qr: qr),
        );
      });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _cash,
            icon: const Icon(Icons.payments_outlined, size: 18),
            label: const Text('Took cash'),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: ElevatedButton.icon(
            onPressed: _busy ? null : _qr,
            icon: const Icon(Icons.qr_code_2, size: 18),
            label: const Text('Show UPI QR'),
          ),
        ),
      ],
    );
  }
}

/// The QR a customer scans, and the moment it is paid.
///
/// The stall's copy of the rider app's sheet, and stateful for the same reason:
/// a sheet that captures the QR and never looks at the order again leaves the
/// person holding the phone with no idea the money has arrived.
///
/// Public rather than private only so a widget test can mount it on its own.
class StallUpiQrSheet extends StatefulWidget {
  const StallUpiQrSheet({super.key, required this.orderId, required this.qr});

  final String orderId;
  final UpiQr qr;

  @override
  State<StallUpiQrSheet> createState() => StallUpiQrSheetState();
}

class StallUpiQrSheetState extends State<StallUpiQrSheet> {
  /// Slower than the rider app's three seconds, because this app holds a socket
  /// and qr_code.credited is published down it. This is only insurance against
  /// that socket having dropped while the sheet is open, and a stall's order
  /// list is a heavier read than a rider's two deliveries.
  static const _whileWatching = Duration(seconds: 6);

  Timer? _poll;

  /// So the buzz fires once rather than on every rebuild after payment.
  bool _announced = false;

  @override
  void initState() {
    super.initState();
    _poll = Timer.periodic(_whileWatching, (_) {
      context.read<OrdersState>().reloadQuietly();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  /// The order as the server last described it, or null if it has gone.
  Order? _current(OrdersState state) {
    for (final o in state.orders) {
      if (o.id == widget.orderId) return o;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final order = _current(context.watch<OrdersState>());

    // A missing order counts as settled rather than still owing. Staring at a
    // live code for an order that is no longer in the queue would be asking a
    // customer to pay for something already closed.
    final paid = order == null || !order.isAwaitingCollection;

    if (paid && !_announced) {
      _announced = true;
      _poll?.cancel();
      // Haptic as well as visual: the phone is turned towards the customer, so
      // the owner is watching them rather than the screen.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        HapticFeedback.heavyImpact();
      });
    }

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: paid ? _paidView(order) : _qrView(),
      ),
    );
  }

  Widget _paidView(Order? order) {
    final how = order?.collectedVia == 'cash' ? 'in cash' : 'by UPI';
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.check_circle, size: 64, color: AppTheme.success),
        const SizedBox(height: 12),
        Text(
          '\u20b9${widget.qr.amount.toStringAsFixed(0)} received',
          style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 4),
        Text(
          'Paid $how. You can hand the order over.',
          textAlign: TextAlign.center,
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Done'),
          ),
        ),
      ],
    );
  }

  Widget _qrView() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '\u20b9${widget.qr.amount.toStringAsFixed(0)}',
          style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 4),
        const Text(
          'Ask the customer to scan with any UPI app',
          style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
        ),
        const SizedBox(height: 16),
        // Razorpay renders the image; our API fetches it and sends the bytes,
        // so showing a code needs nothing of this phone but the API it is
        // already talking to. UpiQrImage picks bytes over link.
        UpiQrImage(qr: widget.qr),
        const SizedBox(height: 16),
        const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(
              height: 14,
              width: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            SizedBox(width: 10),
            Text(
              'Waiting for the payment',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          'This screen tells you the moment it arrives. '
          'The code works until ${TimeOfDay.fromDateTime(widget.qr.expiresAt.toLocal()).format(context)}.',
          textAlign: TextAlign.center,
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ),
      ],
    );
  }
}
