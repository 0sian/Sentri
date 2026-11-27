# Sentri (Android)

Phone side of Sentri: trackpad and keyboard for your PC, plus the AI companion. Talks to the PC daemon over a WebSocket
(`ws://`, port 8765, HMAC challenge-response; the token is never sent). Full project context: `CLAUDE.md` in the repo root.

## Build (command line, no Android Studio)
Requirements: JDK 17 or newer (21 works), Android SDK with `platforms;android-35` and `build-tools;34.0.0`.
Create `local.properties` with `sdk.dir=/path/to/android-sdk` (or export `ANDROID_HOME`), then:

    ./gradlew :app:testDebugUnitTest      # JVM unit tests (chat reducer, sender, face engine, spend, WoL)
    ./gradlew :app:assembleDebug          # app/build/outputs/apk/debug/app-debug.apk

The Gradle wrapper pins Gradle 8.14.3. Install with `adb install -r app/build/outputs/apk/debug/app-debug.apk`.

## Signing
Builds are signed with `app/debug.keystore` if that file exists. It is deliberately not in git. Keep your copy safe:
APKs signed with a different key cannot be installed over each other without uninstalling (which wipes the pairing).

## Layout (app/src/main/java/uk/osianj/companion)
- `Link.kt`: WebSocket, auth, reconnect, ping/RTT, capability handshake, `reconnect()`
- `CompanionViewModel.kt`: prefs + app state (connection, chat, voice, computer-use, guide, saved spend)
- `MainActivity.kt`: top bar, burger menu, screens (Companion, Controller, Settings)
- `ControllerScreen.kt`: trackpad gestures, typing, key strip, shortcuts, media
- `CompanionScreen.kt`: the character canvas and screen
- `Face.kt`: the face engine (expressions, transitions, blink, gaze). Plain Kotlin, unit-tested
- `ChatModel.kt`: chat state reducer (pure, tested), computer-use session state, tool labels, spend helpers
- `ChatDispatcher.kt`: gets a chat message to the PC; reconnect-first, pending/failed/tap-to-resend, answer timeout
- `ChatUi.kt`: chat transcript, approval cards, input
- `CuBanner.kt`: computer-use banner and screen-guide banner
- `Voice.kt`: tap-to-talk with Android's speech recogniser
- `Wol.kt`: Wake-on-LAN magic packet
- `SettingsScreen.kt`, `Theme.kt`
