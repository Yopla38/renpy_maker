package fr.yopla.histoire

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/** Démarre le moteur Python une seule fois et renvoie le port du serveur local. */
object Engine {
    private val lock = Any()
    @Volatile
    private var port = 0

    fun start(context: Context): Int = synchronized(lock) {
        if (port == 0) {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(context.applicationContext))
            }
            // Données de l'histoire : dossier privé de l'application (jamais partagé, jamais sur un serveur).
            val home = File(context.filesDir, "histoire").absolutePath
            port = Python.getInstance().getModule("launcher").callAttr("start", home, 8765).toInt()
        }
        port
    }
}
