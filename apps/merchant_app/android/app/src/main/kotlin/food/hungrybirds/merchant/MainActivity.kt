package food.hungrybirds.merchant

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
        createOrdersChannel()
    }

    /**
     * The channel new-order notifications land on.
     *
     * It has to exist before one arrives. The backend sends channel_id "orders"
     * and the manifest names it as the default, but naming a channel does not
     * create it - Android would quietly fall back to a low-importance default
     * channel, and a phone sitting on a counter would stay silent through a
     * lunch rush with nothing anywhere to explain why.
     *
     * Written here rather than through a notifications plugin on purpose: it is
     * twenty lines against another dependency and its desugaring requirements,
     * in a build that cannot be compiled on the machine this was written on.
     *
     * Creating a channel twice is a no-op, and importance can only be lowered by
     * the user after the first create - so this is safe to run on every start.
     */
    private fun createOrdersChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val channel = NotificationChannel(
            "orders",
            "New orders",
            // HIGH, so it makes a sound and shows as a heads-up banner. This is
            // the whole point: a stall needs to notice during service.
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "A student has placed and paid for an order."
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
