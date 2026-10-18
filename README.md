# MobilePilot updates

Public signed release packages for MobilePilot. This repository contains no proprietary adapter source or private keys.

- APK files are publicly downloadable. Release builds use R8 and stripped native symbols; these measures do not make an APK impossible to analyze.
- `.mpp` files contain encrypted MobilePilot-owned adapters and are sealed for one licensed phone's Keystore public key.
- Update manifests are signed by the existing MobilePilot publisher and bind the device, APK certificate, version, size and SHA256.
- Ownership labels identify release provenance. They do not prevent AI reverse engineering or extraction by a privileged operator from a running device.
- Upstream openpilot, Carrot and Sunnypilot repositories and their phone-side build flow are independent.

Only signed APKs, encrypted payloads, signed update manifests and release notes are published here. The private MobilePilot source repository and signing keys remain private.
