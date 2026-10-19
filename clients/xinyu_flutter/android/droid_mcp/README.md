# droid-mcp in-process SDK subset

Source: https://github.com/stixez/droid-mcp, tag **v0.11.0**, commit
`38723823a05852d3b2a655f48d817fc4bd3b406c`. Apache-2.0; see LICENSE.

The Kotlin files are copied unchanged. UPSTREAM.json records each original path
and SHA-256. XinYu uses the upstream ToolRegistry, InProcessTransport, schema
generation and Android tool implementations. It does not start an MCP HTTP server.
Network transports, the sample app, shell/root/Shizuku, and unrelated data modules
are not included. Registration and permissions are owned by XinYu's PhoneBridge
and existing SQLite automation configuration/action ledger.

The local Gradle file and manifest are integration files, not upstream copies.
They use XinYu's existing AGP/Kotlin toolchain and do not merge all module
permissions. Only selected tools are registered; copied code is not automatically
exposed. The feature is gated at Android 9/API 28, upstream's minimum, while the
rest of XinYu retains its existing minimum Android version.

To refresh from a clean checkout at the pinned revision, run:

```powershell
python clients/xinyu_flutter/tool/vendor_droid_mcp.py <upstream-checkout>
```

Review changes in tool contracts, permissions and tests before changing the pin.
