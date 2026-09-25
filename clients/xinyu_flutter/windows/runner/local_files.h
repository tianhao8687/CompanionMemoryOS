#ifndef XINYU_LOCAL_FILES_H_
#define XINYU_LOCAL_FILES_H_
#include <flutter/method_channel.h>
#include <flutter/encodable_value.h>
#include <windows.h>
#include <memory>

std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> CreateLocalFilesChannel(
    flutter::BinaryMessenger* messenger, HWND window);
#endif
