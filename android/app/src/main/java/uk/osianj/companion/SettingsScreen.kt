package uk.osianj.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun SettingsScreen(vm: CompanionViewModel, onDone: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 22.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (!vm.isPaired) {
            Text("Pair with your PC", color = TextMain, fontSize = 24.sp, fontWeight = FontWeight.SemiBold)
            Text(
                "Start the daemon on your PC. It prints its address and a pairing token - enter both here once.",
                color = TextDim, fontSize = 14.sp,
            )
        }

        SectionLabel("Connection")
        OutlinedTextField(
            value = vm.host, onValueChange = { vm.host = it },
            label = { Text("PC address") }, placeholder = { Text("192.168.1.50") },
            singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        )
        OutlinedTextField(
            value = vm.port, onValueChange = { vm.port = it.filter(Char::isDigit) },
            label = { Text("Port") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        )
        var showToken by remember { mutableStateOf(false) }
        OutlinedTextField(
            value = vm.token, onValueChange = { vm.token = it },
            label = { Text("Pairing token") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false, keyboardType = KeyboardType.Password),
            visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                TextButton(onClick = { showToken = !showToken }) {
                    Text(if (showToken) "Hide" else "Show", color = TextDim, fontSize = 13.sp)
                }
            },
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = { vm.saveAndConnect(); onDone() },
                enabled = vm.host.isNotBlank() && vm.token.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Ink),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.height(50.dp),
            ) { Text(if (vm.isPaired) "Save & reconnect" else "Connect", fontWeight = FontWeight.SemiBold) }
            if (vm.isPaired) TextButton(onClick = { vm.revertConnection(); vm.savePrefsOnly(); onDone() }) {
                Text("Back", color = TextDim)
            }
        }

        Spacer(Modifier.height(6.dp))
        SectionLabel("Controller")
        Text("Pointer speed  ·  ${"%.1f".format(vm.sensitivity)}x", color = TextMain, fontSize = 15.sp)
        Slider(
            value = vm.sensitivity, onValueChange = { vm.sensitivity = it },
            valueRange = 0.5f..3.5f, onValueChangeFinished = { vm.savePrefsOnly() },
        )
        SwitchRow("Natural scrolling", "Content follows your fingers", vm.naturalScroll) {
            vm.naturalScroll = it; vm.savePrefsOnly()
        }
        SwitchRow("Phone volume keys control PC", "Instead of the phone's own volume", vm.volumeKeys) {
            vm.volumeKeys = it; vm.savePrefsOnly()
        }

        Spacer(Modifier.height(6.dp))
        SectionLabel("Character")
        Text("Colour", color = TextDim, fontSize = 13.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BodyColors.forEachIndexed { i, c ->
                val sel = i == vm.charColor
                Box(
                    Modifier
                        .size(38.dp)
                        .clip(CircleShape)
                        .background(c)
                        .border(if (sel) 3.dp else 1.dp, if (sel) TextMain else Hairline, CircleShape)
                        .clickable { vm.charColor = i; vm.savePrefsOnly() },
                )
            }
        }
        Text("Shape", color = TextDim, fontSize = 13.sp)
        OptionRow(ShapeNames, vm.charShape) { vm.charShape = it; vm.savePrefsOnly() }
        Text("Eyes", color = TextDim, fontSize = 13.sp)
        OptionRow(EyeNames, vm.charEyes) { vm.charEyes = it; vm.savePrefsOnly() }
        SwitchRow("White eyes", "White with a thin dark ring. Off gives plain dark eyes", vm.charWhiteEyes) {
            vm.charWhiteEyes = it; vm.savePrefsOnly()
        }
        SwitchRow("Mouth", "Off gives a minimal face", vm.charMouth) {
            vm.charMouth = it; vm.savePrefsOnly()
        }
        val spent = vm.chat.todayUsd
        if (spent != null) {
            Spacer(Modifier.height(6.dp))
            SectionLabel("AI")
            val budget = vm.chat.budgetUsd
            val age = spendAgeLabel(vm.spendAt, System.currentTimeMillis(), java.time.ZoneId.systemDefault())
            Text(
                (if (age == null) "Spent today: $" else "Last reported: $") + "%.3f".format(spent) +
                    (if (budget != null) " of $" + "%.2f".format(budget) else ""),
                color = TextMain, fontSize = 15.sp,
            )
            Text(
                if (age == null) "Reported by your PC after each reply" else "Reported $age \u00B7 updates after your next reply",
                color = TextDim, fontSize = 12.sp,
            )
        }

        Spacer(Modifier.height(10.dp))
        val ctx = LocalContext.current
        val version = remember {
            try { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName } catch (e: Exception) { null }
        }
        Text("Sentri ${version ?: ""}", color = TextDim.copy(alpha = 0.6f), fontSize = 12.sp)
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text.uppercase(), color = Accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp)
}

@Composable
private fun SwitchRow(title: String, sub: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = TextMain, fontSize = 15.sp)
            Text(sub, color = TextDim, fontSize = 12.sp)
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun OptionRow(names: List<String>, selected: Int, onSelect: (Int) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        names.forEachIndexed { i, name ->
            val sel = i == selected
            val shape = RoundedCornerShape(14.dp)
            Box(
                Modifier
                    .height(40.dp)
                    .clip(shape)
                    .background(if (sel) Accent else Panel)
                    .border(1.dp, if (sel) Accent else Hairline, shape)
                    .clickable { onSelect(i) }
                    .padding(horizontal = 18.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(name, color = if (sel) Ink else TextMain, fontSize = 14.sp, fontWeight = FontWeight.Medium)
            }
        }
    }
}
