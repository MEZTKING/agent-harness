package com.meztking.roundtable.data

import android.content.Context
import android.os.Build
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.time.Instant
import com.meztking.roundtable.Brand

/**
 * When the app crashes, what happened is written to a file before Android closes it. On the next
 * start the app opens in a safe mode (nothing loads by itself) and offers to send the details to the
 * owner's PC through the hub, so a crash on the phone can be fixed without a cable or a log viewer.
 */
object Crash {
    private const val FILE = "last-crash.txt"

    fun install(ctx: Context, version: String) {
        val before = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching { File(ctx.filesDir, FILE).writeText(report(error, thread.name, version)) }
            before?.uncaughtException(thread, error)
        }
    }

    fun report(error: Throwable, thread: String, version: String): String {
        val trace = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()
        return buildString {
            appendLine("${Brand.NAME} phone app $version crashed at ${Instant.now()}")
            appendLine("Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}), ${Build.MANUFACTURER} ${Build.MODEL}, thread $thread")
            appendLine()
            append(trace.take(12_000))
        }
    }

    fun last(ctx: Context): String? = File(ctx.filesDir, FILE).takeIf { it.isFile }?.readText()

    fun clear(ctx: Context) { File(ctx.filesDir, FILE).delete() }
}
