package com.altry.app

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(message: String) : Exception(message)

data class Voice(val id: String, val name: String, val duration: Double, val source: String)
data class CatalogVoice(
    val id: String, val name: String, val language: String, val license: String, val credit: String,
    val installed: Boolean,
)
data class Language(val code: String, val name: String)
data class Health(val version: String, val device: String, val separation: Boolean)
data class Job(
    val id: String, val type: String, val title: String, val status: String, val progress: Float,
    val stage: String, val error: String?, val result: String?,
) {
    val active get() = status == "queued" || status == "running"
}

/** A file picked by the user, streamed straight from its content Uri. */
data class Upload(val field: String, val uri: Uri)

/** Blocking client for the Altry server. Call from a background dispatcher. */
class Api(private val context: Context, private val settings: Settings) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(5, TimeUnit.MINUTES)
        .build()

    val baseUrl: String
        get() {
            val raw = settings.serverUrl.trim().trimEnd('/')
            if (raw.isEmpty()) throw ApiException("Önce Ayarlar'dan sunucu adresini girin")
            return if (raw.startsWith("http://") || raw.startsWith("https://")) raw else "http://$raw"
        }

    val authHeaders: Map<String, String>
        get() = if (settings.token.isBlank()) emptyMap() else mapOf("X-Altry-Token" to settings.token.trim())

    private fun request(path: String): Request.Builder = try {
        Request.Builder().url("$baseUrl/api$path").apply { authHeaders.forEach { (k, v) -> header(k, v) } }
    } catch (e: IllegalArgumentException) {
        throw ApiException("Sunucu adresi geçersiz")
    }

    private fun <T> call(request: Request, read: (okhttp3.Response) -> T): T {
        val response = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw ApiException("Sunucuya ulaşılamadı: ${e.message ?: e.javaClass.simpleName}")
        }
        response.use {
            if (!it.isSuccessful) {
                val body = it.body?.string().orEmpty()
                val detail = runCatching { JSONObject(body).get("detail").toString() }.getOrNull()
                throw ApiException(detail ?: "Sunucu hatası (${it.code})")
            }
            return read(it)
        }
    }

    private fun text(request: Request): String = call(request) { it.body?.string().orEmpty() }

    private fun multipart(fields: Map<String, String>, uploads: List<Upload>, onProgress: (Float) -> Unit): RequestBody {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
        fields.forEach { (k, v) -> body.addFormDataPart(k, v) }
        val resolver = context.contentResolver
        val total = uploads.sumOf { sizeOf(resolver, it.uri).coerceAtLeast(0) }
        var sent = 0L
        uploads.forEach { upload ->
            body.addFormDataPart(upload.field, nameOf(resolver, upload.uri), UriBody(resolver, upload.uri) { n ->
                sent += n
                if (total > 0) onProgress((sent.toFloat() / total).coerceAtMost(1f))
            })
        }
        if (fields.isEmpty() && uploads.isEmpty()) return ByteArray(0).toRequestBody()
        return body.build()
    }

    fun health(): Health {
        val json = JSONObject(text(request("/health").build()))
        val engines = json.getJSONObject("engines")
        return Health(json.getString("version"), engines.getString("device"), engines.getBoolean("separation"))
    }

    fun languages(): List<Language> = JSONArray(text(request("/languages").build())).map {
        Language(it.getString("code"), it.getString("name"))
    }

    fun voices(): List<Voice> = JSONArray(text(request("/voices").build())).map(::voice)

    fun catalog(): List<CatalogVoice> = JSONArray(text(request("/voices/catalog").build())).map {
        CatalogVoice(
            it.getString("id"), it.getString("name"), it.getString("language"), it.getString("license"),
            it.getString("credit"), it.getBoolean("installed"),
        )
    }

    fun addVoice(name: String, uri: Uri): Voice = voice(JSONObject(text(
        request("/voices").post(multipart(mapOf("name" to name, "consent" to "true"), listOf(Upload("file", uri))) {}).build()
    )))

    fun addVoiceFromUrl(name: String, url: String): Voice = voice(JSONObject(text(
        request("/voices/from-url").post(multipart(mapOf("name" to name, "url" to url, "consent" to "true"), emptyList()) {}).build()
    )))

    fun installCatalogVoice(id: String) {
        text(request("/voices/catalog/$id").post(ByteArray(0).toRequestBody()).build())
    }

    fun deleteVoice(id: String) {
        text(request("/voices/$id").delete().build())
    }

    fun sampleUrl(id: String) = "$baseUrl/api/voices/$id/sample"

    fun startJob(kind: String, fields: Map<String, String>, uploads: List<Upload>, onProgress: (Float) -> Unit): Job =
        job(JSONObject(text(request("/jobs/$kind").post(multipart(fields, uploads, onProgress)).build())))

    fun jobs(): List<Job> = JSONArray(text(request("/jobs").build())).map(::job)

    fun deleteJob(id: String) {
        text(request("/jobs/$id").delete().build())
    }

    /** Downloads a finished job's file into the cache and returns it. */
    fun download(job: Job): File {
        val dir = File(context.cacheDir, "results").apply { mkdirs() }
        val target = File(dir, "${job.id}_${job.result ?: "sonuc"}")
        if (target.exists() && target.length() > 0) return target
        val partial = File(dir, target.name + ".part")
        call(request("/jobs/${job.id}/result").build()) { response ->
            partial.outputStream().use { out -> response.body!!.byteStream().copyTo(out) }
        }
        if (!partial.renameTo(target)) throw ApiException("Dosya kaydedilemedi")
        return target
    }

    private fun voice(o: JSONObject) =
        Voice(o.getString("id"), o.getString("name"), o.optDouble("duration", 0.0), o.optString("source"))

    private fun job(o: JSONObject) = Job(
        o.getString("id"), o.getString("type"), o.getString("title"), o.getString("status"),
        o.optDouble("progress", 0.0).toFloat(), o.optString("stage"),
        if (o.isNull("error")) null else o.getString("error"),
        if (o.isNull("result")) null else o.getString("result"),
    )

    private fun <T> JSONArray.map(transform: (JSONObject) -> T): List<T> =
        (0 until length()).map { transform(getJSONObject(it)) }
}

private fun queryColumn(resolver: ContentResolver, uri: Uri, column: String): String? = runCatching {
    resolver.query(uri, arrayOf(column), null, null, null)?.use { cursor ->
        if (cursor.moveToFirst() && !cursor.isNull(0)) cursor.getString(0) else null
    }
}.getOrNull()

fun nameOf(resolver: ContentResolver, uri: Uri): String =
    queryColumn(resolver, uri, OpenableColumns.DISPLAY_NAME) ?: uri.lastPathSegment?.substringAfterLast('/') ?: "dosya"

private fun sizeOf(resolver: ContentResolver, uri: Uri): Long =
    if (uri.scheme == "file") File(uri.path.orEmpty()).length()
    else queryColumn(resolver, uri, OpenableColumns.SIZE)?.toLongOrNull() ?: -1

private class UriBody(
    private val resolver: ContentResolver,
    private val uri: Uri,
    private val onBytes: (Long) -> Unit,
) : RequestBody() {
    override fun contentType(): MediaType? = (resolver.getType(uri) ?: "application/octet-stream").toMediaTypeOrNull()
    override fun contentLength(): Long = sizeOf(resolver, uri)
    override fun writeTo(sink: BufferedSink) {
        val input = resolver.openInputStream(uri) ?: throw IOException("Dosya açılamadı")
        input.source().use { source ->
            while (true) {
                val read = source.read(sink.buffer, 64 * 1024L)
                if (read == -1L) break
                sink.emitCompleteSegments()
                onBytes(read)
            }
        }
    }
}
