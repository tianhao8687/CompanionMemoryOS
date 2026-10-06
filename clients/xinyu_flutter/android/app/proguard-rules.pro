# Python resolves this bridge by its class and method names via java.jclass.
# R8 cannot see those references in the bundled Python bytecode.
-keep class com.xinyu.xinyu_flutter.DeviceCredentials { *; }
