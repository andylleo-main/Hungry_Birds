/** Prices come back from the API as decimal strings ("60.00"). */
export function rupees(amount: string | number): string {
  const value = typeof amount === 'number' ? amount : Number.parseFloat(amount);
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

/** Stored E.164 (+919876543210) rendered as 98765 43210. */
export function displayPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '');
  const local = digits.length === 12 && digits.startsWith('91') ? digits.slice(2) : digits;
  if (local.length !== 10) return phone;
  return `${local.slice(0, 5)} ${local.slice(5)}`;
}

/**
 * Client-side mirror of the backend's phone rules, for instant form feedback.
 * The backend re-validates and normalizes, so it stays the source of truth.
 */
export function validateIndianMobile(input: string): string | null {
  const digits = input.replace(/\D/g, '');
  let local = digits;
  if (local.length === 12 && local.startsWith('91')) local = local.slice(2);
  else if (local.length === 11 && local.startsWith('0')) local = local.slice(1);

  if (!local) return 'Enter your phone number';
  if (local.length !== 10 || !/^[6-9]/.test(local)) {
    return 'Enter a valid 10-digit Indian mobile number';
  }
  return null;
}

export function timeOfDay(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

export function dayAndTime(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/** Deterministic fallback art so stalls without a photo still look intentional. */
export function placeholderGradient(seed: string): string {
  const warm = [
    'from-[#FFF0F1] to-[#FFD3D8]',
    'from-[#FFFFFF] to-[#FFE3E6]',
    'from-[#FDE8E8] to-[#F9C6CC]',
    'from-[#FFF5F5] to-[#FFDCDC]',
  ];
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return warm[hash % warm.length];
}
