cmake_minimum_required(VERSION 3.22.1)
project(video_english_learning_whisper)

set(WHISPER_ROOT ${CMAKE_CURRENT_LIST_DIR}/../../../../third_party/whisper.cpp)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(WHISPER_ALL_WARNINGS OFF CACHE BOOL "" FORCE)
set(GGML_ALL_WARNINGS OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_CPU_HBM OFF CACHE BOOL "" FORCE)
set(GGML_CPU_AARCH64 ON CACHE BOOL "" FORCE)

add_subdirectory(
    ${WHISPER_ROOT}
    ${CMAKE_CURRENT_BINARY_DIR}/whisper
)

add_library(whisper_jni SHARED whisper_jni.cpp)

target_include_directories(whisper_jni PRIVATE
    ${WHISPER_ROOT}/include
    ${WHISPER_ROOT}/ggml/include
)

target_link_libraries(whisper_jni
    whisper
    android
    log
)
