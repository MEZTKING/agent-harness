# The test key

`debug.keystore` signs **test builds** of Roundtable Mobile (the APKs attached to releases and sent
for trying out). It's Android's standard debug key (store and key password `android`, alias
`androiddebugkey`): not a secret, never used for the official release. It's kept here so every test
build is signed the same way and installs over the last one without uninstalling.

The official release key is separate and never in git (`mobile/signing/`, or the
`ROUNDTABLE_KEYSTORE_*` repository secrets).
