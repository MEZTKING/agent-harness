package com.meztking.roundtable

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Fable's item 1 (1.5.0): nothing of the app – the keys' store, the runtime, drafts, the chat's own copy – leaves
 *  the phone by cloud backup or device transfer. */
class BackupRulesTest {
    @Test fun nothingLeavesByBackupOrTransfer() {
        val m = File("src/main/AndroidManifest.xml").readText()
        assertTrue(m.contains("android:allowBackup=\"false\""))
        assertTrue(m.contains("android:dataExtractionRules=\"@xml/data_extraction_rules\""))
        assertTrue(m.contains("android:fullBackupContent=\"false\""))
        val r = File("src/main/res/xml/data_extraction_rules.xml").readText()
        for (part in listOf("cloud-backup", "device-transfer")) {
            val block = r.substringAfter("<$part>").substringBefore("</$part>")
            for (d in listOf("root", "file", "database", "sharedpref", "external")) assertTrue("$part $d", block.contains("domain=\"$d\" path=\".\""))
        }
    }
}
