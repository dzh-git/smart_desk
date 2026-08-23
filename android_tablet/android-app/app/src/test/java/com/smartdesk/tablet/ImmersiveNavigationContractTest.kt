package com.smartdesk.tablet

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class ImmersiveNavigationContractTest {
    private val mainActivity = File(
        "src/main/java/com/smartdesk/tablet/MainActivity.kt"
    ).readText()

    @Test
    fun hidesThreeButtonNavigationWhileKeepingSwipeRecovery() {
        assertTrue(
            mainActivity.contains("hide(WindowInsetsCompat.Type.navigationBars())")
        )
        assertTrue(
            mainActivity.contains(
                "WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE"
            )
        )
        assertTrue(mainActivity.contains("override fun onWindowFocusChanged"))
        assertTrue(mainActivity.contains("override fun onResume"))
    }
}
