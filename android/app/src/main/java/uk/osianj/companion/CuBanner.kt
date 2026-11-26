package uk.osianj.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

/**
 * Shown on every screen while the AI has a computer-use session: it is looking at the PC screen and
 * clicking. Red on purpose. Stop ends it at once; touching the trackpad also takes over.
 */
@Composable
fun CuBanner(vm: CompanionViewModel) {
    val cu = vm.cu
    val note = vm.cuNote
    if (cu == null && note == null) return

    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(cu) {
        while (cu != null) { now = System.currentTimeMillis(); delay(500) }
    }
    LaunchedEffect(note, cu) {
        if (note != null && cu == null) { delay(4000); vm.cuNote = null }
    }

    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp)
            .clip(shape)
            .background(if (cu != null) Bad.copy(alpha = 0.16f) else Panel)
            .border(1.dp, if (cu != null) Bad.copy(alpha = 0.7f) else Hairline, shape)
            .padding(start = 14.dp, end = 6.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(Modifier.weight(1f)) {
            if (cu != null) {
                val left = ((cu.endAtMs - now) / 1000L).coerceAtLeast(0L)
                Text(
                    "COMPUTER USE · %d:%02d left".format(left / 60, left % 60),
                    color = Bad, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
                )
                if (cu.goal.isNotEmpty()) Text(cu.goal, color = TextMain, fontSize = 14.sp, maxLines = 2)
                Text("Touch the trackpad to take over", color = TextDim, fontSize = 11.sp)
            } else {
                Text(note.orEmpty(), color = TextDim, fontSize = 13.sp)
            }
        }
        if (cu != null) {
            Box(
                Modifier
                    .height(40.dp)
                    .width(72.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(Bad)
                    .clickable { vm.stopCu() },
                contentAlignment = Alignment.Center,
            ) {
                Text("Stop", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** Shown while the AI is pointing something out on the PC screen. Dismiss removes it from the PC at once. */
@Composable
fun GuideBanner(vm: CompanionViewModel) {
    if (!vm.guide) return
    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp)
            .clip(shape)
            .background(Accent.copy(alpha = 0.14f))
            .border(1.dp, Accent.copy(alpha = 0.6f), shape)
            .padding(start = 14.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Pointing something out on your PC screen", color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
        Box(
            Modifier
                .height(40.dp)
                .width(72.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Panel)
                .border(1.dp, Hairline, RoundedCornerShape(12.dp))
                .clickable { vm.clearGuide() },
            contentAlignment = Alignment.Center,
        ) {
            Text("Clear", color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}
