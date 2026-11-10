package com.altry.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent { AltryTheme { AltryApp() } }
    }
}

private val Colors = darkColorScheme(
    primary = Color(0xFFB69CFF),
    onPrimary = Color(0xFF22005D),
    primaryContainer = Color(0xFF4B2BB0),
    onPrimaryContainer = Color(0xFFE9DDFF),
    secondary = Color(0xFFFF8FB8),
    background = Color(0xFF101014),
    surface = Color(0xFF101014),
    surfaceVariant = Color(0xFF24242C),
    surfaceContainer = Color(0xFF1A1A20),
    surfaceContainerHigh = Color(0xFF22222A),
    surfaceContainerHighest = Color(0xFF2A2A33),
)

@Composable
fun AltryTheme(content: @Composable () -> Unit) = MaterialTheme(colorScheme = Colors, content = content)

enum class Tab(val label: String) { Studio("Stüdyo"), Voices("Sesler"), Jobs("İşler"), Settings("Ayarlar") }

enum class Tool(val title: String, val description: String) {
    Dub("Video dublajı", "Videoyu başka bir dile çevirip aynı sesle yeniden seslendirir"),
    VoiceChange("Ses değiştir", "Videodaki ya da ses kaydındaki konuşmayı seçtiğin sese dönüştürür"),
    Speak("Metni seslendir", "Yazdığını klonlanmış sesle söyletir, istersen bir videonun üzerine koyar"),
    CreateVideo("Sıfırdan video üret", "Metinden seslendirmeli, altyazılı video hazırlar"),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AltryApp(model: AppModel = viewModel()) {
    var tab by rememberSaveable { mutableStateOf(if (model.settings.serverUrl.isBlank()) Tab.Settings else Tab.Studio) }
    var tool by rememberSaveable { mutableStateOf<Tool?>(null) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(model.message) {
        model.message?.let {
            snackbar.showSnackbar(it)
            model.message = null
        }
    }
    BackHandler(enabled = tool != null && tab == Tab.Studio) { tool = null }

    val inTool = tab == Tab.Studio && tool != null
    Scaffold(
        topBar = {
            Column {
                TopAppBar(
                    title = { Text(if (inTool) tool!!.title else if (tab == Tab.Studio) "Altry" else tab.label) },
                    navigationIcon = {
                        if (inTool) IconButton(onClick = { tool = null }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Geri")
                        }
                    },
                )
                model.busy?.let { label ->
                    val uploading = label.startsWith("Yükleniyor") && model.uploadProgress > 0f
                    if (uploading) LinearProgressIndicator(progress = { model.uploadProgress }, Modifier.fillMaxWidth())
                    else LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(
                        if (uploading) "$label %${(model.uploadProgress * 100).toInt()}" else label,
                        Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
        },
        bottomBar = {
            NavigationBar {
                val running = model.jobs.count { it.active }
                Tab.entries.forEach { item ->
                    NavigationBarItem(
                        selected = tab == item,
                        onClick = { tab = item; if (item == Tab.Jobs) model.refreshJobs() },
                        label = { Text(item.label) },
                        icon = {
                            val icon = when (item) {
                                Tab.Studio -> Icons.Filled.Home
                                Tab.Voices -> Icons.Filled.Person
                                Tab.Jobs -> Icons.AutoMirrored.Filled.List
                                Tab.Settings -> Icons.Filled.Settings
                            }
                            if (item == Tab.Jobs && running > 0) {
                                BadgedBox(badge = { Badge { Text("$running") } }) { Icon(icon, contentDescription = null) }
                            } else Icon(icon, contentDescription = null)
                        },
                    )
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Surface(Modifier.fillMaxSize().padding(padding)) {
            val toJobs = { tool = null; tab = Tab.Jobs }
            when (tab) {
                Tab.Studio -> when (tool) {
                    null -> StudioHome(model, onOpen = { tool = it }, onSettings = { tab = Tab.Settings })
                    Tool.Dub -> DubScreen(model, toJobs)
                    Tool.VoiceChange -> VoiceChangeScreen(model, toJobs) { tab = Tab.Voices }
                    Tool.Speak -> SpeakScreen(model, toJobs) { tab = Tab.Voices }
                    Tool.CreateVideo -> CreateVideoScreen(model, toJobs) { tab = Tab.Voices }
                }
                Tab.Voices -> VoicesScreen(model)
                Tab.Jobs -> JobsScreen(model)
                Tab.Settings -> SettingsScreen(model)
            }
        }
    }
}
