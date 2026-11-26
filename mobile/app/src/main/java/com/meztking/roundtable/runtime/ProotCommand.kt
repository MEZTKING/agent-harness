// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/ProotCommand.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import java.io.File

/**
 * The command line and environment that run Roundtable inside proot.
 *
 * DSH Mobile's proot invocation (its runtime README's "Running" section), with Roundtable's own binds: the
 * roundtable layer (kept in its own directory) at `/opt/roundtable`, the persistent `/root` (Roundtable's
 * home, `/root/.roundtable`) and `/workspaces` (the projects), and the generated `resolv.conf` and
 * `/proc/stat`. Pure, so the exact argv is a unit-tested value.
 *
 * **The launch token is never on the command line** (where `ps` shows it) **nor in a file**: it is in the
 * process environment only, which proot hands to Roundtable unchanged. Everything inherited from Android is
 * cleared ([removeFromEnvironment]) so nothing of the app's own environment leaks in.
 */
data class ProotCommand(val argv: List<String>, val environment: Map<String, String>, val removeFromEnvironment: Set<String>) {

    /** Names only: the environment holds the launch token. */
    override fun toString() = "ProotCommand(argv=$argv, environment=${environment.keys})"

    data class Inputs(
        val nativeLibraryDir: File,
        val layout: RuntimeLayout,
        val record: InstalledRecord,
        val port: Int,
        /** ROUNDTABLE_LAUNCH_TOKEN: new each start, only ever in the environment. */
        val launchToken: String,
        /** The names of the app process's own environment, all cleared for the guest. */
        val inherited: Set<String> = emptySet(),
        /** The owner's choices Roundtable reads at start (ROUNDTABLE_ASK_FIRST); never a secret. */
        val extra: Map<String, String> = emptyMap(),
    )

    companion object {
        const val PROOT = "libproot.so"
        const val LOADER = "libproot-loader.so"
        const val GUEST_HOME = "/root"
        const val GUEST_ROUNDTABLE_HOME = "/root/.roundtable"
        const val GUEST_WORKSPACES = "/workspaces"
        const val GUEST_OPT = "/opt/roundtable"
        const val GENERATED_RESOLV = "resolv.conf"
        const val GENERATED_PROC_STAT = "proc-stat"
        const val TOKEN_ENV = "ROUNDTABLE_LAUNCH_TOKEN" // the default; the manifest names it (runtime.launchTokenEnv)

        private const val GUEST_PATH = "/opt/roundtable/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

        /** The fixed script Roundtable runs under: umask, its home, then the program itself from "$@". */
        const val GUEST_WRAPPER = "umask 022; mkdir -p $GUEST_ROUNDTABLE_HOME; exec \"\$@\""

        /**
         * The command, wrapped in `/system/bin/sh` so the first line of output is proot's pid.
         *
         * `echo $$; exec "$@"` prints the shell's pid and then becomes proot in place, so the pid is proot's
         * own. Android's `Process` hides its pid before API 33, and the stop sequence needs it.
         */
        fun build(inputs: Inputs): ProotCommand {
            val layout = inputs.layout
            val record = inputs.record
            val rootfs = File(layout.root, record.base.dir)
            val roundtable = File(layout.root, record.roundtable.dir)
            val argv = buildList {
                add("/system/bin/sh")
                add("-c")
                add("echo \$\$; exec \"\$@\"")
                add("sh")
                add(File(inputs.nativeLibraryDir, PROOT).path)
                add("--kill-on-exit")
                add("--link2symlink")
                add("-0")
                add("-r"); add(rootfs.path)
                add("-b"); add("/dev")
                add("-b"); add("/proc")
                add("-b"); add("/sys")
                add("-b"); add("/proc/self/fd:/dev/fd")
                add("-b"); add("${File(rootfs, "tmp").path}:/dev/shm")
                for (fake in record.fakeProc) {
                    val source = if (fake.target == "/proc/stat") File(layout.run, GENERATED_PROC_STAT) else File(rootfs, fake.source.removePrefix("/"))
                    add("-b"); add("${source.path}:${fake.target}")
                }
                add("-b"); add("${File(layout.run, GENERATED_RESOLV).path}:${record.resolvConf}")
                add("-b"); add("${layout.home.path}:$GUEST_HOME")
                add("-b"); add("${layout.workspaces.path}:$GUEST_WORKSPACES")
                add("-b"); add("${File(roundtable, GUEST_OPT.removePrefix("/")).path}:$GUEST_OPT")
                add("-w"); add(GUEST_HOME)
                add("/bin/sh"); add("-c"); add(GUEST_WRAPPER); add("sh")
                // The manifest's start command: `roundtable phone serve --local --port {port} --home /root/.roundtable`.
                add(record.entrypoint)
                record.args.forEach { add(it.replace("{port}", inputs.port.toString())) }
            }
            val environment = linkedMapOf(
                "PROOT_LOADER" to File(inputs.nativeLibraryDir, LOADER).path,
                "PROOT_TMP_DIR" to layout.prootTmp.path,
                "HOME" to GUEST_HOME,
                "USER" to "root",
                "LOGNAME" to "root",
                "PATH" to GUEST_PATH,
                "LANG" to "C.UTF-8",
                "TERM" to "dumb",
                "TMPDIR" to "/tmp",
                "PYTHONUNBUFFERED" to "1",
            )
            environment.putAll(record.env)
            environment.putAll(inputs.extra)
            environment[record.launchTokenEnv] = inputs.launchToken
            // PROOT_NO_SECCOMP makes proot slower and breaks git's rename path; never inherit it.
            val remove = (inputs.inherited + setOf("PROOT_NO_SECCOMP", "LD_PRELOAD")) - environment.keys
            return ProotCommand(argv, environment, remove)
        }

        /**
         * `resolv.conf` from the active network's DNS servers.
         *
         * glibc reads at most three `nameserver` lines. IPv4 first, since an emulator or a network
         * without IPv6 routing answers IPv6 resolvers with a timeout. Public resolvers are the
         * fallback when the device reports none (no network yet, or a VPN that hides them).
         */
        fun resolvConf(dnsServers: List<String>): String {
            val clean = dnsServers
                .map { it.trim().removePrefix("/").substringBefore('%') }
                .filter { it.isNotEmpty() && it.all { c -> c.isLetterOrDigit() || c == '.' || c == ':' } }
                .distinct()
            val ordered = clean.filter { ':' !in it } + clean.filter { ':' in it }
            val servers = ordered.ifEmpty { FALLBACK_DNS }.take(3)
            return buildString {
                append("# Written by Roundtable Mobile at start from the device's DNS servers.\n")
                servers.forEach { append("nameserver ").append(it).append('\n') }
            }
        }

        val FALLBACK_DNS = listOf("8.8.8.8", "1.1.1.1")

        /**
         * `/proc/stat` with one `cpuN` line per CPU, in the format of the file the base ships.
         *
         * Lines the shipped file has after the CPU lines (`intr`, `ctxt`, `btime`, ...) are kept as
         * they are. Without a shipped file to copy, a minimal one in the same format is written.
         */
        fun procStat(shipped: String?, cpuCount: Int): String {
            val count = cpuCount.coerceIn(1, 1024)
            val perCpu = "500 0 250 8000 12 0 6 0 0 0"
            val lines = shipped?.lines()?.filter { it.isNotBlank() }.orEmpty()
            val template = lines.firstOrNull { CPU_N.containsMatchIn(it) }?.substringAfter(' ')?.trim() ?: perCpu
            val rest = lines.filterNot { it.startsWith("cpu") }
                .ifEmpty { listOf("intr 0", "ctxt 0", "btime 0", "processes 1", "procs_running 1", "procs_blocked 0", "softirq 0 0 0 0 0 0 0 0 0 0 0") }
            val fields = template.split(Regex("\\s+")).map { it.toLongOrNull() ?: 0L }
            val total = fields.map { it * count }.joinToString(" ")
            return buildString {
                append("cpu  ").append(total).append('\n')
                for (i in 0 until count) append("cpu").append(i).append(' ').append(template).append('\n')
                rest.forEach { append(it).append('\n') }
            }
        }

        private val CPU_N = Regex("^cpu\\d+ ")
    }
}
