package com.xinyu.xinyu_flutter

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.net.URL
import java.util.concurrent.Executors

/** Login remains on NetEase's HTTPS site; neither cookies nor credentials reach the AI. */
object NetEaseAccount {
    const val REQUEST = 6408
    private const val ORIGIN = "https://music.163.com"

    fun current(): JSONObject {
        val unavailable = JSONObject().put("status", "succeeded").put("available", false)
            .put("needs_login", true).put("platform", "android")
            .put("message", "首次需要连接网易云账号，完成后自动读取歌单，无需分享链接。")
        fun networkFailure() = JSONObject().put("status", "failed")
            .put("message", "网易云账号暂时无法核对，请稍后再试，已保留原有连接。")
        try {
            val cookie = CookieManager.getInstance().getCookie(ORIGIN) ?: return unavailable
            if (!cookie.split(';').any { it.trim().startsWith("MUSIC_U=") }) return unavailable
            val connection = URL("$ORIGIN/api/w/nuser/account/get")
                .openConnection() as javax.net.ssl.HttpsURLConnection
            try {
                val deadline = SystemClock.elapsedRealtime() + 3000
                connection.connectTimeout = 1200
                connection.readTimeout = 1200
                connection.instanceFollowRedirects = false
                connection.setRequestProperty("Cookie", cookie)
                connection.setRequestProperty("Referer", "$ORIGIN/")
                if (connection.responseCode != 200) return networkFailure()
                val bytes = connection.inputStream.use { stream ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(4096)
                    while (true) {
                        val remaining = deadline - SystemClock.elapsedRealtime()
                        if (remaining <= 0) return networkFailure()
                        connection.readTimeout = remaining.coerceAtMost(1200).toInt()
                        val count = stream.read(buffer)
                        if (count < 0) break
                        if (output.size() + count > 131072) return networkFailure()
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                }
                val data = JSONObject(String(bytes, Charsets.UTF_8))
                val id = data.optJSONObject("profile")?.optString("userId") ?: ""
                if (data.optInt("code") == 200 && Regex("[1-9][0-9]{0,17}").matches(id)) {
                    return JSONObject().put("status", "succeeded").put("available", true)
                        .put("user_id", id).put("source", "android_connected_account")
                }
            } finally { connection.disconnect() }
        } catch (_: Exception) {
            // Never log account responses or cookie/exception text.
            return networkFailure()
        }
        return unavailable
    }
}

class NetEaseAccountActivity : Activity() {
    private lateinit var web: WebView
    private val handler = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private var stopped = true
    private var checking = false
    private val check = object : Runnable {
        override fun run() {
            if (stopped || checking) return
            checking = true
            worker.execute {
                val connected = NetEaseAccount.current().optBoolean("available")
                handler.post {
                    checking = false
                    if (stopped) return@post
                    if (connected) {
                        CookieManager.getInstance().flush()
                        setResult(RESULT_OK)
                        finish()
                    } else handler.postDelayed(this, 2500)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            fitsSystemWindows = true
        }
        layout.addView(Button(this).apply {
            text = "返回心隅"
            setOnClickListener { finish() }
        })
        layout.addView(TextView(this).apply {
            text = "在网易云官方网页登录一次，随后会自动读取可访问的歌单。"
            textSize = 15f
            setTextColor(Color.DKGRAY)
            setPadding(20, 12, 20, 16)
        })
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            settings.mediaPlaybackRequiresUserGesture = true
            settings.userAgentString = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            // No JavaScript bridge, credential extraction or arbitrary native intent.
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val uri = request.url
                    return uri.scheme != "https" ||
                        (uri.host != "music.163.com" && uri.host != "y.music.163.com")
                }
                override fun onPageFinished(view: WebView, url: String) {
                    if (!stopped && !checking) { handler.removeCallbacks(check); handler.post(check) }
                }
            }
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)
        layout.addView(web, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(layout)
        web.loadUrl("https://music.163.com/#/my/m/music/playlist")
    }

    override fun onResume() { super.onResume(); stopped = false; handler.post(check) }
    override fun onPause() { stopped = true; handler.removeCallbacks(check); super.onPause() }
    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        web.stopLoading()
        web.destroy()
        worker.shutdownNow()
        super.onDestroy()
    }
}
