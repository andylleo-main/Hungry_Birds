package food.hungrybirds.rider

import android.app.NotificationChannel
import android.app.NotificationManager
import android.media.AudioAttributes
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createDeliveriesChannel()
    }

    /**
     * The channel an assignment notification lands on.
     *
     * It has to exist before one arrives. The backend sends channel_id
     * "deliveries" and the manifest names it as the default, but naming a
     * channel does not create it - Android would quietly fall back to a
     * low-importance default, and a rider with the phone in a pocket would
     * never learn they had been given a delivery.
     *
     * Its own id rather than the merchant app's "orders" because a channel is
     * per-app and these are not the same event: a rider muting assignments
     * should not be entangled with anything a stall owner has configured.
     *
     * Creating a channel twice is a no-op, and importance can only be lowered by
     * the user after the first create - so this is safe to run on every start.
     */
    private fun createDeliveriesChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val channel = NotificationChannel(
            "deliveries",
            "New deliveries",
            // HIGH, so it makes a sound and shows as a heads-up banner. A rider
            // who has to unlock the phone to find out is a rider who finds out
            // late.
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "A stall has given you an order to deliver."
            enableVibration(true)
            setSound(
                Settings.System.DEFAULT_NOTIFICATION_URI,
                AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                    .build(),
            )
        }

        val manager = getSystemService(NotificationManager::class.java)
        manager?.createNotificationChannel(channel)
    }
}
