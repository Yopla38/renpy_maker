package fr.yopla.histoire

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * Garde l'application active quand elle passe en arrière-plan : une génération d'images peut durer
 * plusieurs minutes, et Android couperait le moteur sans ce service de premier plan.
 */
class EngineService : Service() {

    override fun onCreate() {
        super.onCreate()
        val channel = "histoire"
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(channel, "Création de l'histoire", NotificationManager.IMPORTANCE_LOW)
        )
        val notification = Notification.Builder(this, channel)
            .setContentTitle("Mon histoire")
            .setContentText("Une création est peut-être en cours")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, notification)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Thread { Engine.start(applicationContext) }.start()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
