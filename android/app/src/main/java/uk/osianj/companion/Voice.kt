package uk.osianj.companion

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Tap-to-talk using the phone's own speech recogniser. Partial words stream into [onPartial]; the
 * final transcript goes to [onFinal]. Must be created and used on the main thread.
 */
class VoiceController(
    private val ctx: Context,
    private val onPartial: (String) -> Unit,
    private val onFinal: (String) -> Unit,
    private val onError: (String) -> Unit,
    private val onListening: (Boolean) -> Unit,
) {
    var listening by mutableStateOf(false)
        private set

    /** Microphone loudness, 0..1, for the pulsing ring. */
    var level by mutableFloatStateOf(0f)
        private set

    private var rec: SpeechRecognizer? = null

    val available: Boolean get() = SpeechRecognizer.isRecognitionAvailable(ctx)

    private fun set(on: Boolean) {
        if (listening != on) { listening = on; onListening(on) }
        if (!on) level = 0f
    }

    fun start() {
        if (listening) return
        if (!available) { onError("No speech recogniser on this phone"); return }
        destroy()
        val r = SpeechRecognizer.createSpeechRecognizer(ctx)
        rec = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) { level = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f) }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}

            override fun onPartialResults(partialResults: Bundle?) {
                first(partialResults)?.let(onPartial)
            }

            override fun onResults(results: Bundle?) {
                set(false)
                val text = first(results)?.trim().orEmpty()
                if (text.isNotEmpty()) onFinal(text)
            }

            override fun onError(error: Int) {
                set(false)
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH,
                    SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
                    SpeechRecognizer.ERROR_CLIENT -> {} // silence or cancelled: nothing to say
                    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> onError("Microphone permission is off")
                    SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT ->
                        onError("Speech recognition needs a connection")
                    SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> onError("Speech recogniser is busy")
                    else -> onError("Couldn't hear that")
                }
            }
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-GB")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        set(true)
        r.startListening(intent)
    }

    /** Finish now and deliver what was heard. */
    fun stop() { rec?.stopListening() }

    /** Abandon without delivering anything. */
    fun cancel() {
        rec?.cancel()
        set(false)
    }

    fun destroy() {
        rec?.destroy()
        rec = null
        set(false)
    }

    private fun first(b: Bundle?): String? =
        b?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
}
