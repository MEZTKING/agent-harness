// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/test/java/com/labteto/dshmobile/runtime/RuntimeFixture.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.InetAddress

/**
 * A made-up runtime release served over HTTPS from a local server, signed with a test key, plus an app
 * storage layout on a temporary folder: what the installer tests run against. Layers are plain tar here
 * (the decoder is the identity); the device unpacks xz.
 */
class RuntimeFixture(tmp: TemporaryFolder) {
    val key = TestSigningKey()
    val release = ReleaseServer()
    val fs = RecordingFsOps()
    val layout = RuntimeLayout(File(tmp.newFolder("no_backup"), "runtime"), File(tmp.newFolder("cache"), "runtime"))

    @Volatile var freeBytes: Long = 64L shl 30

    private val server = MockWebServer()
    val client: OkHttpClient

    init {
        val names = listOf("localhost", "127.0.0.1") + listOf("localhost", "127.0.0.1").map { InetAddress.getByName(it).canonicalHostName }
        val certificate = HeldCertificate.Builder().apply { names.distinct().forEach { addSubjectAlternativeName(it) } }.build()
        val serverCerts = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientCerts = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        server.useHttps(serverCerts.sslSocketFactory(), false)
        server.dispatcher = release
        server.start()
        client = OkHttpClient.Builder().sslSocketFactory(clientCerts.sslSocketFactory(), clientCerts.trustManager).build()
    }

    fun close() = server.shutdown()

    val source: ManifestSource get() = ManifestSource(server.url("/rel/manifest.json").toString(), server.url("/rel/manifest.json.sig").toString())

    data class Layer(val name: String, val id: String, val bytes: ByteArray, val entries: Int) {
        val file = "roundtable-runtime-$name-x86_64-$id.tar.xz"
    }

    fun baseLayer(id: String = "trixie-test-r1"): Layer {
        val tar = TarBuilder()
            .dir("usr").dir("usr/bin").file("usr/bin/bash", "elf", "755".toInt(8)).symlink("bin", "usr/bin")
            .dir("etc").file("etc/resolv.conf", "nameserver 8.8.8.8\n")
            .dir("root", "700".toInt(8)).dir("tmp", "1777".toInt(8))
        return Layer(LAYER_BASE, id, tar.bytes(), 8)
    }

    fun roundtableLayer(version: String, extra: TarBuilder.() -> Unit = {}): Layer {
        val tar = TarBuilder()
            .dir("opt").dir("opt/roundtable").dir("opt/roundtable/venv").dir("opt/roundtable/venv/bin")
            .file("opt/roundtable/venv/bin/roundtable", "#!/opt/roundtable/venv/bin/python\n", "755".toInt(8))
        tar.extra()
        return Layer(LAYER_ROUNDTABLE, "roundtable-$version", tar.bytes(), 5)
    }

    /** Publish a release: the layers and a manifest describing them, signed by [signer]. */
    fun publish(
        base: Layer,
        roundtable: Layer,
        sequence: Long,
        channel: String = "test",
        signer: TestSigningKey = key,
        keyId: String = ManifestVerifier.keyId(key.rawPublicKey),
        minAppVersion: String = "0.7.0",
        servedBase: ByteArray = base.bytes,
        archKey: String = "x86_64",
    ) {
        release.files["rel/assets/${base.file}"] = servedBase
        release.files["rel/assets/${roundtable.file}"] = roundtable.bytes
        val json = manifestJson(base, roundtable, sequence, channel, keyId, minAppVersion, archKey)
        release.files["rel/manifest.json"] = json.toByteArray()
        release.files["rel/manifest.json.sig"] = signer.signatureFile(json.toByteArray())
    }

    fun installer(appVersion: String = "0.7.3", allowTest: Boolean = true) = RuntimeInstaller(
        layout = layout,
        store = InstalledStore(layout),
        fs = fs,
        client = client,
        downloader = LayerDownloader(client, layout.downloads),
        space = SpaceProbe { freeBytes },
        source = { source },
        appVersion = { appVersion },
        deviceAbis = listOf("x86_64"),
        verifier = ManifestVerifier(listOf(key.rawPublicKey)),
        allowTest = allowTest,
        decoder = { it },
    )

    fun assetRequests(layer: Layer) = release.requestsFor("rel/assets/${layer.file}")

    fun manifestJson(base: Layer, roundtable: Layer, sequence: Long, channel: String, keyId: String, minAppVersion: String, archKey: String = "x86_64"): String {
        fun layer(l: Layer) = """
            {"file": "${l.file}", "size": ${l.bytes.size}, "sha256": "${sha256Hex(l.bytes)}", "name": "${l.name}", "id": "${l.id}",
             "compression": "xz", "unpackedSize": ${l.bytes.size}, "entries": ${l.entries}}
        """.trimIndent()
        return """
            {
              "schemaVersion": 1,
              "product": "roundtable",
              "channel": "$channel",
              "releaseId": "runtime-test-$sequence",
              "sequence": $sequence,
              "minAppVersion": "$minAppVersion",
              "signing": {"algorithm": "Ed25519", "keyId": "$keyId", "signatureFile": "manifest.json.sig"},
              "assetBaseUrl": "${server.url("/rel/assets/")}",
              "harness": {"package": "roundtable-hold", "version": "${roundtable.id.removePrefix("roundtable-")}"},
              "runtime": {
                "entrypoint": "/opt/roundtable/venv/bin/roundtable",
                "args": ["phone", "serve", "--local", "--port", "{port}", "--home", "/root/.roundtable"],
                "env": {"ROUNDTABLE_HOME": "/root/.roundtable", "ROUNDTABLE_WORKSPACES": "/workspaces"},
                "launchTokenEnv": "ROUNDTABLE_LAUNCH_TOKEN",
                "readinessPrefix": "Roundtable is ready on",
                "healthPath": "/api/health",
                "fakeProc": [],
                "resolvConf": "/etc/resolv.conf"
              },
              "archs": {"$archKey": {"debianArch": "amd64", "layers": [${layer(base)}, ${layer(roundtable)}]}}
            }
        """.trimIndent()
    }

    companion object {
        val SHIPPED_STAT = buildString {
            append("cpu  4000 0 2000 64000 100 0 50 0 0 0\n")
            for (i in 0 until 8) append("cpu$i 500 0 250 8000 12 0 6 0 0 0\n")
            append("intr 0\nctxt 0\nbtime 1762732800\nprocesses 1\nprocs_running 1\nprocs_blocked 0\nsoftirq 0 0 0 0 0 0 0 0 0 0 0\n")
        }
    }
}
