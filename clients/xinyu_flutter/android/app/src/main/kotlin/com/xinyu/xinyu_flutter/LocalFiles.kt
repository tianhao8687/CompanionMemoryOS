package com.xinyu.xinyu_flutter

import android.app.Activity
import android.content.Intent
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService

class LocalFiles(private val activity: Activity, private val worker: ExecutorService) {
    private var pending: MethodChannel.Result? = null
    private var bytes: ByteArray? = null
    private val limit = 64 * 1024 * 1024

    fun call(call: MethodCall, result: MethodChannel.Result) {
        if (call.method != "saveBackup" && call.method != "pickBackup") {
            result.notImplemented(); return
        }
        if (pending != null) { result.error("busy", "请先完成文件选择。", null); return }
        val save = call.method == "saveBackup"
        bytes = if (save) call.argument<ByteArray>("bytes") else null
        if (save && (bytes == null || bytes!!.size > limit)) {
            result.error("backup_size", "备份文件无效或超过 64 MB。", null); return
        }
        pending = result
        val intent = Intent(if (save) Intent.ACTION_CREATE_DOCUMENT else Intent.ACTION_OPEN_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(if (save) "application/octet-stream" else "*/*")
        if (save) intent.putExtra(Intent.EXTRA_TITLE, call.argument<String>("name") ?: "xinyu-backup.sqlite")
        try { activity.startActivityForResult(intent, if (save) 7101 else 7102) }
        catch (_: Exception) {
            pending = null; bytes = null
            result.error("file_picker", "无法打开系统文件选择器。", null)
        }
    }

    fun result(request: Int, code: Int, data: Intent?): Boolean {
        if (request != 7101 && request != 7102) return false
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
                            require(output.size() + count <= limit)
                            output.write(buffer, 0, count)
                        }
                    }
                    val content = output.toByteArray()
                    activity.runOnUiThread { reply.success(content) }
                }
            } catch (_: Exception) {
                activity.runOnUiThread { reply.error("backup_file", "无法读写备份，请检查文件权限和大小（最多 64 MB）。", null) }
            }
        }
        return true
    }
}
