package com.altry.app

import android.app.Application
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("altry", Context.MODE_PRIVATE)
    var serverUrl: String
        get() = prefs.getString("server", "") ?: ""
        set(value) = prefs.edit().putString("server", value).apply()
    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(value) = prefs.edit().putString("token", value).apply()
}

const val ORIGINAL_VOICE = "original"

class AppModel(app: Application) : AndroidViewModel(app) {
    val settings = Settings(app)
    val api = Api(app, settings)

    var health by mutableStateOf<Health?>(null); private set
    var connectionError by mutableStateOf<String?>(null); private set
    var languages by mutableStateOf(listOf(Language("tr", "Türkçe"), Language("en", "English"))); private set
    var voices by mutableStateOf(emptyList<Voice>()); private set
    var catalog by mutableStateOf(emptyList<CatalogVoice>()); private set
    var jobs by mutableStateOf(emptyList<Job>()); private set

    /** Non-null while something is in flight; shown as a blocking progress line. */
    var busy by mutableStateOf<String?>(null); private set
    var uploadProgress by mutableStateOf(0f); private set
    /** One-shot message for the snackbar. */
    var message by mutableStateOf<String?>(null)

    init {
        if (settings.serverUrl.isNotBlank()) connect()
        viewModelScope.launch {
            while (true) {  // poll quickly while a job is running, slowly otherwise
                delay(if (jobs.any { it.active }) 2000 else 8000)
                if (health != null) runCatching { withContext(Dispatchers.IO) { api.jobs() } }.onSuccess { jobs = it }
            }
        }
    }

    private fun run(label: String?, block: suspend () -> Unit) {
        viewModelScope.launch {
            if (label != null) busy = label
            try {
                block()
            } catch (e: ApiException) {
                message = e.message
            } catch (e: Exception) {
                message = "Hata: ${e.message ?: e.javaClass.simpleName}"
            } finally {
                if (label != null) busy = null
            }
        }
    }

    private suspend fun <T> io(block: () -> T): T = withContext(Dispatchers.IO) { block() }

    fun connect() = run("Sunucuya bağlanılıyor…") {
        try {
            health = io { api.health() }
            connectionError = null
            languages = io { api.languages() }
            voices = io { api.voices() }
            jobs = io { api.jobs() }
            catalog = io { api.catalog() }
        } catch (e: ApiException) {
            health = null
            connectionError = e.message
        }
    }

    fun saveSettings(url: String, token: String) {
        settings.serverUrl = url.trim()
        settings.token = token.trim()
        connect()
    }

    fun refreshJobs() = run(null) { jobs = io { api.jobs() } }

    fun addVoice(name: String, uri: Uri, onDone: () -> Unit = {}) = run("Ses klonlanıyor…") {
        io { api.addVoice(name, uri) }
        voices = io { api.voices() }
        message = "“$name” sesi eklendi"
        onDone()
    }

    fun addVoiceFromUrl(name: String, url: String) = run("Ses indiriliyor…") {
        io { api.addVoiceFromUrl(name, url) }
        voices = io { api.voices() }
        message = "“$name” sesi eklendi"
    }

    fun installCatalogVoice(item: CatalogVoice) = run("Ses indiriliyor…") {
        io { api.installCatalogVoice(item.id) }
        voices = io { api.voices() }
        catalog = io { api.catalog() }
        message = "“${item.name}” eklendi"
    }

    fun deleteVoice(voice: Voice) = run(null) {
        io { api.deleteVoice(voice.id) }
        voices = io { api.voices() }
        catalog = io { api.catalog() }
    }

    fun startJob(kind: String, fields: Map<String, String>, uploads: List<Upload>, onStarted: () -> Unit) =
        run(if (uploads.isEmpty()) "Gönderiliyor…" else "Yükleniyor…") {
            uploadProgress = 0f
            io { api.startJob(kind, fields, uploads) { uploadProgress = it } }
            jobs = io { api.jobs() }
            onStarted()
        }

    fun deleteJob(job: Job) = run(null) {
        io { api.deleteJob(job.id) }
        jobs = io { api.jobs() }
    }

    private fun mimeOf(file: File): String =
        MimeTypeMap.getSingleton().getMimeTypeFromExtension(file.extension.lowercase()) ?: "*/*"

    private fun shareUri(file: File): Uri {
        val context = getApplication<Application>()
        return FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    }

    fun openResult(job: Job, share: Boolean) = run("İndiriliyor…") {
        val file = io { api.download(job) }
        val uri = shareUri(file)
        val intent = if (share) {
            Intent(Intent.ACTION_SEND).setType(mimeOf(file)).putExtra(Intent.EXTRA_STREAM, uri)
        } else {
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, mimeOf(file))
        }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        val chooser = Intent.createChooser(intent, if (share) "Paylaş" else "Aç").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        getApplication<Application>().startActivity(chooser)
    }

    val canSaveToGallery get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

    /** Copies the result into Movies/Altry or Music/Altry so it shows up in the gallery. */
    fun saveResult(job: Job) = run("Kaydediliyor…") {
        val file = io { api.download(job) }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return@run
        val isVideo = mimeOf(file).startsWith("video")
        io {
            val resolver = getApplication<Application>().contentResolver
            val collection = if (isVideo) MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            else MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, "altry_${file.name}")
                put(MediaStore.MediaColumns.MIME_TYPE, mimeOf(file))
                put(
                    MediaStore.MediaColumns.RELATIVE_PATH,
                    (if (isVideo) Environment.DIRECTORY_MOVIES else Environment.DIRECTORY_MUSIC) + "/Altry",
                )
            }
            val target = resolver.insert(collection, values) ?: throw ApiException("Galeriye kaydedilemedi")
            resolver.openOutputStream(target)!!.use { out -> file.inputStream().use { it.copyTo(out) } }
        }
        message = if (isVideo) "Movies/Altry klasörüne kaydedildi" else "Music/Altry klasörüne kaydedildi"
    }
}
