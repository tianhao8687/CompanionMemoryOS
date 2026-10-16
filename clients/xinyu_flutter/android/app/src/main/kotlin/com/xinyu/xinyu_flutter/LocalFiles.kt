package com.xinyu.xinyu_flutter

import android.app.Activity
import android.content.Intent
import android.provider.MediaStore
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService

class LocalFiles(private val activity: Activity, private val worker: ExecutorService) {
    private var pending: MethodChannel.Result? = null
    private var bytes: ByteArray? = null
    private val limit = 64 * 1024 * 1024

    fun call(call: MethodCall, result: MethodChannel.Result) {
        if (call.method !in setOf("saveBackup", "pickBackup", "pickImage", "pickPersona")) {
            result.notImplemented(); return
        }
        if (pending != null) { result.error("busy", "请先完成文件选择。", null); return }
        val image = call.method == "pickImage"
        val persona = call.method == "pickPersona"
        val save = call.method == "saveBackup"
        bytes = if (save) call.argument<ByteArray>("bytes") else null
        if (save && (bytes == null || bytes!!.size > limit)) {
            result.error("backup_size", "备份文件无效或超过 64 MB。", null); return
        }
        pending = result
        // Resolve capabilities, never handset brands. Updated systems expose
        // Photo Picker; older devices open their gallery through ACTION_PICK.
        val photoPicker = Intent("android.provider.action.PICK_IMAGES").setType("image/*")
        val intent = if (image) {
            if (photoPicker.resolveActivity(activity.packageManager) != null) photoPicker
            else Intent(Intent.ACTION_PICK, MediaStore.Images.Media.EXTERNAL_CONTENT_URI).setType("image/*")
        } else {
            Intent(if (save) Intent.ACTION_CREATE_DOCUMENT else Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType(if (save) "application/octet-stream" else "*/*")
                .apply { if (persona) putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/json", "image/png", "text/plain")) }
        }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        if (save) intent.putExtra(Intent.EXTRA_TITLE, call.argument<String>("name") ?: "xinyu-backup.sqlite")
        try { activity.startActivityForResult(intent, if (save) 7101 else if (image) 7103 else if (persona) 7104 else 7102) }
        catch (_: Exception) {
            pending = null; bytes = null
            result.error("file_picker", if (image) "无法打开系统图库，请检查相册应用是否可用。" else "无法打开系统文件选择器。", null)
        }
    }

    fun result(request: Int, code: Int, data: Intent?): Boolean {
        if (request !in 7101..7104) return false
        val reply = pending ?: return true
        val payload = bytes
        pending = null; bytes = null
        val uri = data?.data
        if (code != Activity.RESULT_OK || uri == null) {
            reply.success(if (request == 7101) false else null); return true
        }
        worker.execute {
            try {
                if (request == 7101) {
                    activity.contentResolver.openOutputStream(uri, "wt").use { stream ->
                        requireNotNull(stream).write(requireNotNull(payload))
                    }
                    activity.runOnUiThread { reply.success(true) }
                } else {
                    val output = ByteArrayOutputStream()
                    activity.contentResolver.openInputStream(uri).use { stream ->
                        requireNotNull(stream)
                        val buffer = ByteArray(65536)
                        while (true) {
                            val count = stream.read(buffer)
                            if (count < 0) break
                            require(output.size() + count <= if (request >= 7103) 20 * 1024 * 1024 else limit)
                            output.write(buffer, 0, count)
                        }
                    }
                    val content = output.toByteArray()
                    activity.runOnUiThread { reply.success(content) }
                }
            } catch (_: Exception) {
                activity.runOnUiThread { reply.error("local_file", if (request >= 7103) "无法读取内容，请选择 20 MB 以内的文件。" else "无法读写备份，请检查文件权限和大小（最多 64 MB）。", null) }
            }
        }
        return true
    }
}
