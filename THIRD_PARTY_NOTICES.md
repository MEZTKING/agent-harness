# Third-party notices

Code in Roundtable Hold that was taken or ported from other projects, with each
project's licence. Roundtable Hold itself is MIT.

## dsh-plugin-save-token 2.1.3

- Source: the DeepSeek Harness plugin `dsh-plugin-save-token` (npm package, also
  github.com/vibe-any/dsh-plugin-save-token), file `src/index.js`.
- Ported to Python in `src/roundtable/harness/saver.py`: the token estimate (`estTokens`),
  the TOON-style re-encoding of uniform JSON arrays (`uniformKeys`, `toonEncode`,
  `findDominantUniformArray`), the structural JSON shortening (`transformValue`), the
  line compressor and its table mode (`collapseBlanks`, `collapseRepeats`,
  `trimLongLines`, `delimiterProfile`, `looksTabular`, `windowLines`,
  `windowLinesStrided`, the error-line pattern), the never-worse gate
  (`buildCandidate`), spill-before-replace, the cross-turn dedupe and the expand tool
  (`save_token_expand`, here `expand_output`), with the plugin's default settings
  (`cordis.patch.yml`). Its dashboard and its compaction trigger were not taken.
- The plugin system (`src/roundtable/plugins/`) follows the shape of DeepSeek Harness's
  plugins as seen in this package (a hook on tool results, hooks around model calls,
  registered tools, web routes, settings with defaults); no code was copied for it. The
  token saver now runs behind it as the built-in plugin `token-saver`
  (`plugins/builtin/token_saver.py`).

```
MIT License

Copyright (c) 2026 PlayWithAI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Fonts: Space Grotesk, Inter and JetBrains Mono

- Used by the Eclipse look on the desktop (`src/roundtable/ui/static/space-grotesk.woff2`,
  `inter.woff2`, `inter-italic.woff2`, `jetbrains-mono.woff2`: the Latin variable files from the
  npm packages `@fontsource-variable/space-grotesk`, `@fontsource-variable/inter` and
  `@fontsource-variable/jetbrains-mono` 5.3.0, unchanged) and on the phone
  (`mobile/app/src/main/res/font/space_grotesk_600.ttf`, `space_grotesk_700.ttf`, `inter_400.ttf`,
  `inter_600.ttf`, `inter_700.ttf`, `jetbrains_mono_400.ttf`: fixed weights made from the same
  files). Served from the app itself; nothing is loaded from outside.
- Space Grotesk: Copyright 2020 The Space Grotesk Project Authors (https://github.com/floriankarsten/space-grotesk).
- Inter: Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter).
- JetBrains Mono: Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono).
- Fraunces and Nunito Sans (the Candlelit Oak look's fonts) were shipped up to 0.12.0 and are no
  longer included.
- All three under the SIL Open Font License, Version 1.1:

```
This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

## DSH Mobile: the on-phone runtime ("This phone")

- Source: DSH Mobile (the owner's fork `MEZTKING/deepseek-harness-mobile`), MIT.
- Taken and adapted into `mobile/app/src/main/java/com/meztking/roundtable/runtime/` (package renamed,
  trimmed: no update coordinator, resume-after-update, Files provider, Termux or relay), each file
  marked with its source at the top: from `app/src/main/java/com/labteto/dshmobile/runtime/`
  `AndroidRuntimeSystem.kt`, `AppVersion.kt`, `FsOps.kt`, `HarnessLog.kt`, `HarnessProcess.kt`,
  `HarnessRuntimeService.kt`, `HarnessSupervisor.kt`, `LayerDownloader.kt`, `ManifestPolicy.kt`,
  `ManifestVerifier.kt`, `ProotCommand.kt`, `RuntimeInstaller.kt`, `RuntimeLayout.kt`,
  `RuntimeManifest.kt`, `TarExtractor.kt`; and their tests from `app/src/test/java/com/labteto/dshmobile/runtime/`
  (`RuntimeTestSupport.kt`, `RuntimeFixture.kt`, `TarExtractorTest.kt`, `LayerDownloaderTest.kt`,
  `ProotBinariesTest.kt`, `HarnessSupervisorTest.kt`, `ManifestVerifierTest.kt`, `ManifestPolicyTest.kt`,
  `ProotCommandTest.kt`, `RuntimeInstallerTest.kt`). `mobile/app/third_party/proot/` is DSH's record of
  the proot binaries, unchanged.
### DSH Mobile: the in-app updater

- Source: the owner's MIT fork of DSH Mobile, its in-app updater under
  `app/src/main/java/com/labteto/dshmobile/update/`.
- Adapted in Roundtable Mobile's updater (`mobile/app/src/main/java/com/meztking/roundtable/update/`):
  the version compare (`UpdateChecker.kt` `isNewerVersion` → `Releases.kt` `isNewerVersion`), the
  file hash (`Checksums.kt` `sha256Of` → `Releases.kt` `sha256Of`), the PackageInstaller session and
  its status receiver (`PackageInstallerGateway.kt` `PackageInstallerGateway.commit`,
  `UpdateInstallReceiver` → `Installer.kt` `Installer.commit`, `InstallReceiver`), the install
  failures told apart (`InstallStatus.kt` `mapInstallStatus` → `Installer.kt` `installFailureText`),
  and the resume rules of the download (`ResumableDownloader.kt` `planResponse` → `AppUpdater.kt`
  `fetchOnce`, simplified). The wording and the screens are Roundtable's own.

```
MIT License

Copyright (c) 2026 DSH Mobile contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### DSH Mobile: the Browser tab and the runtime update's trial (wave 8, 1.4.0)

- `mobile/app/src/main/java/com/meztking/roundtable/data/browser/BrowserAddress.kt` – copied unchanged but its
  package from `core/src/commonMain/kotlin/com/labteto/dshmobile/core/browser/BrowserAddress.kt`.
- `mobile/app/src/main/java/com/meztking/roundtable/data/browser/BrowserReach.kt` – adapted from
  `core/src/commonMain/kotlin/com/labteto/dshmobile/core/browser/BrowserReach.kt` and `MentionedAddresses.kt`
  (the connections are This phone, a paired PC and Hub mode; the words are the app's).
- `mobile/app/src/test/java/com/meztking/roundtable/data/browser/BrowserAddressTest.kt` and `WebLinkTest.kt` –
  ported from `core/src/commonTest/kotlin/com/labteto/dshmobile/core/browser/BrowserAddressTest.kt` and
  `WebLinkTest.kt`, run through the app's `KotlinTestShim.kt`.
- `mobile/app/src/main/java/com/meztking/roundtable/ui/browser/BrowserScreen.kt` – the WebView's settings and the
  refusal of other apps' links follow `app/src/main/java/com/labteto/dshmobile/ui/screens/main/browser/BrowserView.kt`;
  the screen is the app's own.
- `mobile/app/src/main/java/com/meztking/roundtable/runtime/RuntimeInstaller.kt` and `RuntimeLayout.kt` – the
  update trial and its rollback (`commitTrial`, `rollbackTrial`) follow DSH Mobile's same files.

MIT License, Copyright (c) 2026 DSH Mobile contributors (the licence text is above).

## proot and talloc (shipped as separate programs in the phone app)

Roundtable Mobile ships `libproot.so` and `libproot-loader.so` for `arm64-v8a` and `x86_64` in
`mobile/app/src/main/jniLibs/`, byte for byte the ones DSH Mobile ships (prebuilt by
`sorsama/dsh-mobile-runtime`, release `2026.11.14-1`; hashes and provenance in
`mobile/app/third_party/proot/`). They are separate executables the app starts; they are not linked
into the app.

- proot: https://github.com/termux/proot, commit `52d65a4dc140ca554d241a1438ddd4f6b00c9813`
  (5.1.107.102). Licence: GPL-2.0-or-later.
- talloc 2.5.0 (linked statically into proot): https://talloc.samba.org. Licence: LGPL-3.0-or-later.
- Complete corresponding source: `proot-source-52d65a4dc140ca554d241a1438ddd4f6b00c9813.tar.gz` and
  `talloc-source-2.5.0.tar.gz`, attached to
  https://github.com/sorsama/dsh-mobile-runtime/releases/tag/2026.11.14-1.

## EdDSA-Java and XZ for Java (phone app dependencies, not vendored)

- EdDSA-Java 0.3.0 (`net.i2p.crypto:eddsa`) checks the runtime manifest's Ed25519 signature on
  Android 8 to 12. https://github.com/str4d/ed25519-java. Licence: CC0 1.0 (public domain dedication).
- XZ for Java 1.10 (`org.tukaani:xz`) unpacks the runtime's `.tar.xz` layers. https://tukaani.org/xz/java.html.
  Licence: 0BSD.

## pypdf (a dependency of the desktop app, not vendored)

- pypdf (`pypdf>=4`) reads the text of a PDF for search and the Files tab (`src/roundtable/documents.py`); the
  Windows build bundles it. https://github.com/py-pdf/pypdf. Licence: BSD-3-Clause, Copyright (c) 2006-2008,
  Mathieu Fenniak; some contributions copyright (c) 2007, Ashish Kulkarni; some contributions copyright (c) 2014,
  Steve Witham; all rights reserved (the full text ships with the package, `pypdf-*.dist-info/licenses/LICENSE`).

## Munder Difflin (MEZTKING/munder-difflin), MIT, Copyright (c) 2026 Chaitanya Giri

Ported to Python or used as the pattern, credited in each file's header:
- `src/roundtable/harness/breaker.py` – the circuit breaker's policy (steer, then constrain, then stop; the
  defaults; the tool-call key) from `src/main/breaker.ts`.
- `src/roundtable/automation.py` – schedules (catch-up window, early wake, a schedule's own time zone, the
  "Weekdays at 09:00" summary) from `src/shared/weeklySchedule.ts`.
- `src/roundtable/prereq.py` – the shape of the tools catalogue from `src/shared/toolCatalog.ts` and
  `src/main/toolsStatus.ts`.
- `src/roundtable/mcp_catalogue.json` – the tool servers' package names and pinned versions (data only) from
  `src/shared/mcpCatalog.ts`, checked there on 14 October 2026; the descriptions and wording are the harness's own.
- `src/roundtable/memory.py` – the memory's design (rules never moved, capped pinned notes, recent notes moved
  word for word to an archive, the check that memory.md loses only whole lines) from `src/main/reflect.ts` and
  `src/shared/memoryShape.ts`; no code was copied.
Its pixel art and other assets (LICENSE-ASSETS) are not used.

```
MIT License

Copyright (c) 2026 Chaitanya Giri

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### DSH Mobile: the automation wording

- `src/roundtable/ui/static/automation.js` `inWords` – the next-run words from
  `app/src/main/java/com/labteto/dshmobile/ui/screens/main/AutomationPresentation.kt` (MIT, Copyright (c) 2026
  DSH Mobile contributors; licence text above).
