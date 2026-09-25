cmake_minimum_required(VERSION 3.22.1)
project(xinyu_sqlite LANGUAGES C)

if(NOT EXISTS "${XINYU_SQLITE_SOURCE}")
    message(FATAL_ERROR "Run prepare_android_sqlite.py and set XINYU_SQLITE_SOURCE to sqlite3.c")
endif()

# Keep the same SQLite version/SONAME used by Chaquopy's CPython 3.13 binding.
# Add its missing FTS5 module; all memory tables and evidence stay in one SQLite DB.
add_library(sqlite3_python SHARED "${XINYU_SQLITE_SOURCE}")
target_compile_definitions(sqlite3_python PRIVATE
    SQLITE_ENABLE_FTS5=1
    SQLITE_ENABLE_MATH_FUNCTIONS=1
    SQLITE_THREADSAFE=1
)
target_compile_options(sqlite3_python PRIVATE -O2)
target_link_options(sqlite3_python PRIVATE -Wl,-z,max-page-size=16384 -Wl,--strip-all)
target_link_libraries(sqlite3_python PRIVATE m dl)
