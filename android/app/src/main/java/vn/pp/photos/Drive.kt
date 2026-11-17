package vn.pp.photos

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class DFile(val id: String, val name: String, val isFolder: Boolean, val modified: String = "")

/** Gọi Google Drive REST bằng token do Google Sign-In cấp. `refresh` xin token mới khi hết hạn (HTTP 401). */
object Drive {
    var token: String = ""
    var refresh: (suspend () -> String?)? = null
    private const val API = "https://www.googleapis.com/drive/v3"
    private const val UP = "https://www.googleapis.com/upload/drive/v3"

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private suspend fun call(method: String, url: String, body: ByteArray? = null, ctype: String? = null, retry: Boolean = true): ByteArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 20000
        c.readTimeout = 60000
        c.setRequestProperty("Authorization", "Bearer $token")
        if (body != null) {
            c.doOutput = true
            c.setRequestProperty("Content-Type", ctype ?: "application/octet-stream")
            c.outputStream.use { it.write(body) }
        }
        val code = c.responseCode
        if (code == 401 && retry && refresh != null) {
            val t = refresh!!.invoke()
            if (!t.isNullOrEmpty()) {
                token = t
                return call(method, url, body, ctype, false)
            }
        }
        if (code !in 200..299) {
            val err = c.errorStream?.readBytes()?.toString(Charsets.UTF_8) ?: ""
            throw RuntimeException("Drive $code: ${err.take(200)}")
        }
        return c.inputStream.use { it.readBytes() }
    }

    suspend fun list(parentId: String): List<DFile> {
        val out = ArrayList<DFile>()
        var page: String? = null
        do {
            val q = enc("'$parentId' in parents and trashed=false")
            var url = "$API/files?q=$q&fields=${enc("nextPageToken,files(id,name,mimeType,modifiedTime)")}&pageSize=1000"
            if (page != null) url += "&pageToken=${enc(page)}"
            val j = JSONObject(call("GET", url).toString(Charsets.UTF_8))
            val arr = j.getJSONArray("files")
            for (i in 0 until arr.length()) {
                val f = arr.getJSONObject(i)
                out.add(DFile(f.getString("id"), f.getString("name"), f.optString("mimeType") == "application/vnd.google-apps.folder", f.optString("modifiedTime")))
            }
            page = if (j.has("nextPageToken")) j.getString("nextPageToken") else null
        } while (page != null)
        return out
    }

    /** Tìm mọi thư mục có tên này trong Drive của bạn (mới nhất trước). */
    suspend fun findFolders(name: String): List<String> {
        val q = enc("name='$name' and mimeType='application/vnd.google-apps.folder' and trashed=false")
        val j = JSONObject(call("GET", "$API/files?q=$q&orderBy=${enc("modifiedTime desc")}&fields=${enc("files(id,name)")}&pageSize=20").toString(Charsets.UTF_8))
        val arr = j.getJSONArray("files")
        return (0 until arr.length()).map { arr.getJSONObject(it).getString("id") }
    }

    suspend fun download(id: String): ByteArray = call("GET", "$API/files/$id?alt=media")

    suspend fun upload(parentId: String, name: String, data: ByteArray) {
        val boundary = "pp" + System.nanoTime()
        val meta = JSONObject().put("name", name).put("parents", org.json.JSONArray().put(parentId)).toString()
        val bo = ByteArrayOutputStream()
        bo.write("--$boundary\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n$meta\r\n--$boundary\r\nContent-Type: application/octet-stream\r\n\r\n".toByteArray())
        bo.write(data)
        bo.write("\r\n--$boundary--".toByteArray())
        call("POST", "$UP/files?uploadType=multipart", bo.toByteArray(), "multipart/related; boundary=$boundary")
    }
}
