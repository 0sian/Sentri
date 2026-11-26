package uk.osianj.companion

import android.graphics.Color as AColor
import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

enum class Screen(val title: String) {
    Companion("Sentri"),
    Controller("Controller"),
    Actions("Quick actions"),
    Settings("Settings"),
}

class MainActivity : ComponentActivity() {
    private val vm: CompanionViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(AColor.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(AColor.TRANSPARENT),
        )
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Accent, onPrimary = Ink,
                    background = Ink, onBackground = TextMain,
                    surface = Panel, onSurface = TextMain,
                    surfaceVariant = Panel, onSurfaceVariant = TextDim,
                    surfaceContainer = Panel, surfaceContainerHigh = Panel,
                    outline = Color(0xFF5A534B), outlineVariant = Hairline,
                )
            ) { App(vm) }
        }
    }

    override fun onStart() {
        super.onStart()
        vm.onForeground()
    }

    override fun onStop() {
        super.onStop()
        vm.onBackground()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (vm.handleHardwareKey(keyCode)) return true
        return super.onKeyDown(keyCode, event)
    }
}

@Composable
fun App(vm: CompanionViewModel) {
    // The companion is the home screen; first run goes straight to pairing.
    var screen by remember { mutableStateOf(if (vm.isPaired) Screen.Companion else Screen.Settings) }
    val state by vm.link.state.collectAsStateWithLifecycle()
    val rtt by vm.link.rtt.collectAsStateWithLifecycle()

    BackHandler(enabled = screen != Screen.Companion) { screen = Screen.Companion }

    Column(
        Modifier
            .fillMaxSize()
            .background(Ink)
            .systemBarsPadding()
            .imePadding()
    ) {
        TopBar(screen, state, rtt, vm, onRetry = { vm.connect() }, onNavigate = { screen = it })
        CuBanner(vm)
        GuideBanner(vm)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (screen) {
                Screen.Companion -> CompanionScreen(vm)
                Screen.Controller -> ControlScreen(vm)
                Screen.Actions -> ActionsScreen(vm)
                Screen.Settings -> SettingsScreen(vm) { screen = Screen.Companion }
            }
        }
    }
}

@Composable
private fun TopBar(
    screen: Screen,
    state: Link.State,
    rtt: Int?,
    vm: CompanionViewModel,
    onRetry: () -> Unit,
    onNavigate: (Screen) -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    val (label, color) = when (state) {
        is Link.State.Idle -> "Not connected" to TextDim
        is Link.State.Connecting -> "Connecting…" to Accent
        is Link.State.Connected ->
            ("Connected · ${state.host}" + (rtt?.let { " · $it ms" } ?: "")) to Good
        is Link.State.Failed -> (state.reason + if (state.retrying) " · retrying" else "") to Bad
    }
    val canRetry = state is Link.State.Idle || (state is Link.State.Failed && !state.retrying)

    Row(
        Modifier.fillMaxWidth().padding(start = 18.dp, end = 8.dp, top = 6.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(screen.title, color = TextMain, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(8.dp))
                Text(vm.wakeNote ?: label, color = TextDim, fontSize = 12.sp, maxLines = 1)
            }
        }
        // Wake-on-LAN, once the daemon has told us the PC's MAC address
        if (state !is Link.State.Connected && vm.pcMac != null && vm.wakeNote == null) {
            TextButton(onClick = { vm.wakePc() }) { Text("Wake PC", color = Accent) }
        }
        if (canRetry) TextButton(onClick = onRetry) { Text("Retry", color = Accent) }

        Box {
            Box(
                Modifier.size(48.dp).clip(CircleShape).clickable { menu = true },
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.size(22.dp)) {
                    val stroke = 2.2.dp.toPx()
                    for (i in 0..2) {
                        val y = size.height * (0.15f + 0.35f * i)
                        drawLine(TextMain, Offset(0f, y), Offset(size.width, y), stroke, StrokeCap.Round)
                    }
                }
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                for (s in Screen.entries) {
                    DropdownMenuItem(
                        text = {
                            Text(
                                s.title,
                                color = if (s == screen) Accent else TextMain,
                                fontWeight = if (s == screen) FontWeight.SemiBold else FontWeight.Normal,
                            )
                        },
                        onClick = { menu = false; onNavigate(s) },
                    )
                }
            }
        }
    }
}
