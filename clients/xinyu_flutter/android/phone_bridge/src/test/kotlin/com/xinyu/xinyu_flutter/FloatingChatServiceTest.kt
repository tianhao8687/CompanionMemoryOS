package com.xinyu.xinyu_flutter

import android.app.Service
import android.content.Intent
import android.os.Looper
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ServiceController
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSettings
import java.time.Duration

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 36], manifest = Config.NONE)
class FloatingChatServiceTest {
    private lateinit var lifecycle: ServiceController<FloatingChatService>
    private lateinit var service: FloatingChatService
    private var stopped = 0
    private val events = mutableListOf<String>()
    @Before fun setup() {
        ShadowSettings.setCanDrawOverlays(true)
        shadowOf(RuntimeEnvironment.getApplication().getSystemService(android.os.PowerManager::class.java)).setIsInteractive(true)
        FloatingChatSession.host = object : FloatingChatSession.Host {
            override fun event(method: String, args: Map<String, Any?>, done: (Boolean) -> Unit) { events += method; done(true) }
            override fun stopped() { stopped++ }
            override fun changed() {}
        }
        FloatingChatSession.update(mapOf("conversation" to "synthetic", "busy" to false))
        lifecycle = Robolectric.buildService(FloatingChatService::class.java).create()
        service = lifecycle.get()
    }
    @After fun cleanup() {
        lifecycle.destroy()
        FloatingChatSession.host = null
        FloatingChatSession.clear()
    }
    @Test fun permissionIsRequiredAndServiceNeverRestartsItself() {
        ShadowSettings.setCanDrawOverlays(false)
        assertEquals(Service.START_NOT_STICKY, service.onStartCommand(Intent(), 0, 1))
        assertTrue(shadowOf(service).isStoppedBySelf)
        assertNull(FloatingChatSession.service)
    }
    @Test fun revocationStopsAnExistingSession() {
        service.onStartCommand(Intent(), 0, 1)
        assertSame(service, FloatingChatSession.service)
        ShadowSettings.setCanDrawOverlays(false)
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
        assertTrue(shadowOf(service).isStoppedBySelf)
    }
    @Test fun closingDuringReplyKeepsRuntimeUntilFinalState() {
        FloatingChatSession.update(mapOf("conversation" to "synthetic", "busy" to true))
        service.onStartCommand(Intent(), 0, 1)
        service.onStartCommand(Intent().setAction(FloatingChatService.CLOSE), 0, 2)
        assertFalse(shadowOf(service).isStoppedBySelf)
        FloatingChatSession.update(mapOf("conversation" to "synthetic", "busy" to false))
        assertTrue(shadowOf(service).isStoppedBySelf)
    }
    @Test fun secondCloseExplicitlyCancelsPendingReply() {
        FloatingChatSession.update(mapOf("conversation" to "synthetic", "busy" to true))
        service.onStartCommand(Intent(), 0, 1)
        val close = Intent().setAction(FloatingChatService.CLOSE)
        service.onStartCommand(close, 0, 2)
        service.onStartCommand(close, 0, 3)
        assertEquals(listOf("cancel"), events)
    }
    @Test fun lockHidesSessionAndDoesNotCollectOtherAppContent() {
        service.onStartCommand(Intent(), 0, 1)
        RuntimeEnvironment.getApplication().sendBroadcast(Intent(Intent.ACTION_SCREEN_OFF))
        shadowOf(Looper.getMainLooper()).idle()
        assertTrue(shadowOf(service).isStoppedBySelf)
        assertTrue(events.isEmpty())
    }
}
