#include "local_files.h"
#include <flutter/standard_method_codec.h>
#include <commdlg.h>
#include <objbase.h>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <vector>

std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> CreateLocalFilesChannel(
    flutter::BinaryMessenger* messenger, HWND window) {
  using flutter::EncodableValue;
  auto channel = std::make_unique<flutter::MethodChannel<EncodableValue>>(
      messenger, "xinyu/local-files", &flutter::StandardMethodCodec::GetInstance());
  channel->SetMethodCallHandler([window](const auto& call, auto result) {
    const bool save = call.method_name() == "saveBackup";
    if (!save && call.method_name() != "pickBackup") { result->NotImplemented(); return; }
    wchar_t path[32768] = L"xinyu-backup.sqlite";
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = window;
    dialog.lpstrFile = path;
    dialog.nMaxFile = 32768;
    dialog.lpstrFilter = L"XinYu backup (*.sqlite)\0*.sqlite\0\0";
    dialog.lpstrDefExt = L"sqlite";
    dialog.Flags = OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST |
        (save ? OFN_OVERWRITEPROMPT : OFN_FILEMUSTEXIST);
    if (!(save ? GetSaveFileNameW(&dialog) : GetOpenFileNameW(&dialog))) {
      if (CommDlgExtendedError()) result->Error("file_dialog", "无法打开文件选择窗口。");
      else result->Success(save ? EncodableValue(false) : EncodableValue());
      return;
    }
    try {
      if (save) {
        const auto& arguments = std::get<flutter::EncodableMap>(*call.arguments());
        const auto& bytes = std::get<std::vector<uint8_t>>(arguments.at(EncodableValue("bytes")));
        if (bytes.size() > 64 * 1024 * 1024) throw std::runtime_error("size");
        // Write beside the selected file, then atomically replace it only on success.
        GUID id;
        if (FAILED(CoCreateGuid(&id))) throw std::runtime_error("temporary file");
        wchar_t identifier[40];
        StringFromGUID2(id, identifier, 40);
        const auto temporary = std::filesystem::path(std::wstring(path) + identifier + L".tmp");
        try {
          std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
          output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
          output.close();
          if (!output || !MoveFileExW(temporary.c_str(), path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            throw std::runtime_error("write");
        } catch (...) { std::filesystem::remove(temporary); throw; }
        result->Success(EncodableValue(true));
      } else {
        const auto size = std::filesystem::file_size(path);
        if (size < 100 || size > 64 * 1024 * 1024) throw std::runtime_error("size");
        std::vector<uint8_t> bytes(static_cast<size_t>(size));
        std::ifstream input(std::filesystem::path(path), std::ios::binary);
        input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
        if (!input) throw std::runtime_error("read");
        result->Success(EncodableValue(bytes));
      }
    } catch (...) { result->Error("backup_file", "无法读写备份文件，请检查权限和文件大小（最多 64 MB）。"); }
  });
  return channel;
}
