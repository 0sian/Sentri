package uk.osianj.companion

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope

class CompanionViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = app.getSharedPreferences("companion", Context.MODE_PRIVATE)

    val link = Link(viewModelScope)

    var host by mutableStateOf(prefs.getString("host", "") ?: "")
    var port by mutableStateOf(prefs.getString("port", "8765") ?: "8765")
    var token by mutableStateOf(prefs.getString("token", "") ?: "")
    var sensitivity by mutableFloatStateOf(prefs.getFloat("sens", 1.5f))
    var naturalScroll by mutableStateOf(prefs.getBoolean("natural", true))
    var volumeKeys by mutableStateOf(prefs.getBoolean("volkeys", false))

    /** One-shot sticky modifiers (ctrl/alt/shift/super) applied to the next key or typed character. */
    val mods = mutableStateListOf<String>()

    val isPaired: Boolean get() = host.isNotBlank() && token.isNotBlank()

    fun saveAndConnect() {
        host = host.trim()
        port = port.trim()
        token = token.trim()
        prefs.edit()
            .putString("host", host).putString("port", port).putString("token", token)
            .putFloat("sens", sensitivity)
            .putBoolean("natural", naturalScroll).putBoolean("volkeys", volumeKeys)
            .apply()
        connect()
    }

    fun savePrefsOnly() {
        prefs.edit()
            .putFloat("sens", sensitivity)
            .putBoolean("natural", naturalScroll).putBoolean("volkeys", volumeKeys)
            .apply()
    }

    fun connect() {
        if (!isPaired) return
        link.connect(host, port.toIntOrNull() ?: 8765, token)
    }

    fun onForeground() {
        if (isPaired && link.state.value is Link.State.Idle) connect()
    }

    fun onBackground() {
        // Drop the socket when the app isn't visible: saves battery and never leaves a stale controller.
        link.disconnect()
    }

    fun handleHardwareKey(keyCode: Int): Boolean {
        if (!volumeKeys || !link.isConnected) return false
        return when (keyCode) {
            android.view.KeyEvent.KEYCODE_VOLUME_UP -> { link.key("volup"); true }
            android.view.KeyEvent.KEYCODE_VOLUME_DOWN -> { link.key("voldown"); true }
            else -> false
        }
    }

    // ---- key helpers that respect sticky modifiers ---------------------
    fun toggleMod(m: String) {
        if (mods.contains(m)) mods.remove(m) else mods.add(m)
    }

    fun pressKey(name: String) {
        link.key(name, mods.toList())
        mods.clear()
    }

    /** Bare tap of a modifier key on its own (e.g. Super to open a launcher). */
    fun tapModAlone(name: String) {
        link.key(name)
        mods.remove(name)
    }

    fun typeText(s: String) {
        if (mods.isNotEmpty() && s.length == 1) {
            link.key(s.lowercase(), mods.toList())
            mods.clear()
        } else {
            link.text(s)
        }
    }

    fun backspace() = link.key("backspace")

    override fun onCleared() {
        link.disconnect()
    }
}
