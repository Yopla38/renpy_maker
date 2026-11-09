package fr.yopla.histoire

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import android.webkit.WebViewClient

/** Affiche l'éditeur (page /facile) servi par le moteur local. */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private val ui = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.builtInZoomControls = false
            webViewClient = WebViewClient()
        }
        setContentView(web)
        startService(Intent(this, EngineService::class.java))
        // Le premier démarrage de Python prend quelques secondes : on ne charge la page qu'après.
        Thread {
            val port = Engine.start(applicationContext)
            ui.post { web.loadUrl("http://127.0.0.1:$port/facile") }
        }.start()
    }

    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        if (isFinishing) stopService(Intent(this, EngineService::class.java))
        super.onDestroy()
    }
}
