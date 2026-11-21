cmake_minimum_required(VERSION 3.24)

project(OctoBeat VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Widgets Svg Network Concurrent)
if(UNIX AND NOT APPLE)
    find_package(Qt6 REQUIRED COMPONENTS DBus)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(ALSA REQUIRED alsa)
endif()
include(GNUInstallDirs)

set(RUST_CORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../rust/core")
set(RUST_AUDIO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../rust/audio-engine")
set(RUST_TARGET "" CACHE STRING "Optional Rust target triple")
set(RUST_CARGO_TARGET_ARGS "")
set(RUST_TARGET_DIR "${CMAKE_BINARY_DIR}/rust-target")
if(RUST_TARGET)
    list(APPEND RUST_CARGO_TARGET_ARGS --target "${RUST_TARGET}")
    set(RUST_OUTPUT_DIR "${RUST_TARGET_DIR}/${RUST_TARGET}")
else()
    set(RUST_OUTPUT_DIR "${RUST_TARGET_DIR}")
endif()
if(WIN32)
    set(RUST_STATIC_PREFIX "")
    set(RUST_STATIC_SUFFIX ".lib")
else()
    set(RUST_STATIC_PREFIX "lib")
    set(RUST_STATIC_SUFFIX ".a")
endif()
set(RUST_CORE_LIB "${RUST_OUTPUT_DIR}/release/${RUST_STATIC_PREFIX}octobeat_core${RUST_STATIC_SUFFIX}")
set(RUST_AUDIO_LIB "${RUST_OUTPUT_DIR}/release/${RUST_STATIC_PREFIX}octobeat_audio${RUST_STATIC_SUFFIX}")

file(GLOB_RECURSE RUST_SOURCES CONFIGURE_DEPENDS
    "${RUST_CORE_DIR}/src/*.rs"
    "${RUST_CORE_DIR}/Cargo.toml")

add_custom_command(
    OUTPUT "${RUST_CORE_LIB}"
    COMMAND ${CMAKE_COMMAND} -E env
            "CARGO_TARGET_DIR=${RUST_TARGET_DIR}"
            cargo build --release ${RUST_CARGO_TARGET_ARGS}
            --manifest-path "${RUST_CORE_DIR}/Cargo.toml"
    DEPENDS ${RUST_SOURCES}
    WORKING_DIRECTORY "${RUST_CORE_DIR}"
    COMMENT "Building OctoBeat Rust core"
    VERBATIM
)

add_custom_target(octobeat_core_build ALL DEPENDS "${RUST_CORE_LIB}")

file(GLOB_RECURSE RUST_AUDIO_SOURCES CONFIGURE_DEPENDS
    "${RUST_AUDIO_DIR}/src/*.rs"
    "${RUST_AUDIO_DIR}/Cargo.toml"
    "${RUST_AUDIO_DIR}/Cargo.lock")

add_custom_command(
    OUTPUT "${RUST_AUDIO_LIB}"
    COMMAND ${CMAKE_COMMAND} -E env
            "CARGO_TARGET_DIR=${RUST_TARGET_DIR}"
            cargo build --release ${RUST_CARGO_TARGET_ARGS}
            --manifest-path "${RUST_AUDIO_DIR}/Cargo.toml"
    DEPENDS ${RUST_AUDIO_SOURCES}
    WORKING_DIRECTORY "${RUST_AUDIO_DIR}"
    COMMENT "Building OctoBeat native audio engine"
    VERBATIM
)

add_custom_target(octobeat_audio_build ALL DEPENDS "${RUST_AUDIO_LIB}")

add_library(octobeat_core STATIC IMPORTED GLOBAL)
set_target_properties(octobeat_core PROPERTIES
    IMPORTED_LOCATION "${RUST_CORE_LIB}"
)
add_dependencies(octobeat_core octobeat_core_build)

add_library(octobeat_audio STATIC IMPORTED GLOBAL)
set_target_properties(octobeat_audio PROPERTIES
    IMPORTED_LOCATION "${RUST_AUDIO_LIB}"
)
add_dependencies(octobeat_audio octobeat_audio_build)

add_executable(octobeat
    src/main.cpp
    src/core/CoreClient.cpp
    src/core/CoreClient.h
    src/core/octobeat_core.h
    src/downloads/FastStreamService.cpp
    src/downloads/FastStreamService.h
    src/downloads/CsvImportDialog.cpp
    src/downloads/CsvImportDialog.h
    src/downloads/DownloadDialog.cpp
    src/downloads/DownloadDialog.h
    src/downloads/DownloadsPage.cpp
    src/downloads/DownloadsPage.h
    src/downloads/StreamingPage.cpp
    src/downloads/StreamingPage.h
    src/downloads/StreamCard.cpp
    src/downloads/StreamCard.h
    src/downloads/StreamCollectionView.cpp
    src/downloads/StreamCollectionView.h
    src/downloads/StreamHomeView.cpp
    src/downloads/StreamHomeView.h
    src/downloads/StreamItemRow.cpp
    src/downloads/StreamItemRow.h
    src/downloads/StreamSearchOverlay.cpp
    src/downloads/StreamSearchOverlay.h
    src/downloads/StreamQueuePanel.cpp
    src/downloads/StreamQueuePanel.h
    src/downloads/StreamSearchView.cpp
    src/downloads/StreamSearchView.h
    src/downloads/SearchResult.h
    src/downloads/StreamHistory.cpp
    src/downloads/StreamHistory.h
    src/downloads/RemoteImageCache.cpp
    src/downloads/RemoteImageCache.h
    src/downloads/SearchCache.cpp
    src/downloads/SearchCache.h
    src/downloads/SomeDlService.cpp
    src/downloads/SomeDlService.h
    src/downloads/StreamCache.cpp
    src/downloads/StreamCache.h
    src/downloads/YouTubeBrowseService.cpp
    src/downloads/YouTubeBrowseService.h
    src/downloads/YouTubeParser.cpp
    src/downloads/YouTubeParser.h
    src/downloads/YouTubeSearchService.cpp
    src/downloads/YouTubeSearchService.h
    src/downloads/YtDlpService.cpp
    src/downloads/YtDlpService.h
    src/audio/AudioEngine.cpp
    src/audio/AudioEngine.h
    src/audio/audio_engine.h
    src/app/TitleBar.cpp
    src/app/TitleBar.h
    src/app/IconUtils.cpp
    src/app/IconUtils.h
    src/app/ResourcePaths.cpp
    src/app/ResourcePaths.h
    src/app/ToolPaths.cpp
    src/app/ToolPaths.h
    src/app/AddTracksDialog.cpp
    src/app/AddTracksDialog.h
    src/app/ClickSlider.cpp
    src/app/ClickSlider.h
    src/app/CoverCache.cpp
    src/app/CoverCache.h
    src/app/ElidedLabel.cpp
    src/app/ElidedLabel.h
    src/app/FullscreenLyrics.cpp
    src/app/FullscreenLyrics.h
    src/app/LyricsButton.cpp
    src/app/LyricsButton.h
    src/app/LyricsPanel.cpp
    src/app/LyricsPanel.h
    src/app/LyricsService.cpp
    src/app/LyricsService.h
    src/app/LibraryPage.cpp
    src/app/LibraryPage.h
    src/app/MiniPlayer.cpp
    src/app/MiniPlayer.h
    src/app/PlayerBar.cpp
    src/app/PlayerBar.h
    src/app/PlaylistCoverDelegate.cpp
    src/app/PlaylistCoverDelegate.h
    src/app/PlaylistsPage.cpp
    src/app/PlaylistsPage.h
    src/app/ProfilePage.cpp
    src/app/ProfilePage.h
    src/app/SettingsPage.cpp
    src/app/SettingsPage.h
    src/app/SmoothListWidget.cpp
    src/app/SmoothListWidget.h
    src/app/SpinnerWidget.cpp
    src/app/SpinnerWidget.h
    src/app/SmoothTreeWidget.cpp
    src/app/SmoothTreeWidget.h
    src/app/TrackDelegate.cpp
    src/app/TrackDelegate.h
    src/app/Theme.cpp
    src/app/Theme.h
    src/app/Translations.cpp
    src/app/Translations.h
    src/app/MainWindow.cpp
    src/app/MainWindow.h
    src/app/LocalizedMessageBox.cpp
    src/app/LocalizedMessageBox.h
    src/app/MprisService.cpp
    src/app/MprisService.h
)

if(WIN32)
    target_compile_definitions(octobeat PRIVATE OCTOBEAT_NO_MPRIS)
    # GUI subsystem: do not open a console window for the desktop app.
    set_target_properties(octobeat PROPERTIES WIN32_EXECUTABLE TRUE)
    set(OCTOBEAT_ICON_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../icons/icon.ico")
    configure_file(
        "${CMAKE_CURRENT_SOURCE_DIR}/octobeat.rc.in"
        "${CMAKE_CURRENT_BINARY_DIR}/octobeat.rc"
        @ONLY
    )
    target_sources(octobeat PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/octobeat.rc")
endif()

if(MSVC)
    # Sources contain UTF-8 UI strings; keep the standard value of __cplusplus.
    target_compile_options(octobeat PRIVATE /utf-8 /Zc:__cplusplus)
endif()

target_include_directories(octobeat PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
if(UNIX AND NOT APPLE)
    target_include_directories(octobeat PRIVATE ${ALSA_INCLUDE_DIRS})
endif()

target_compile_definitions(octobeat PRIVATE
    OCTOBEAT_RESOURCES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/.."
)

if(UNIX AND NOT APPLE)
    target_link_directories(octobeat PRIVATE ${ALSA_LIBRARY_DIRS})
endif()

if(UNIX AND NOT APPLE)
    target_link_libraries(octobeat PRIVATE
        Qt6::Widgets
        Qt6::Svg
        Qt6::Network
        Qt6::Concurrent
        Qt6::DBus
        octobeat_core
        octobeat_audio
        ${ALSA_LIBRARIES}
        dl
        pthread
        m
    )
elseif(WIN32)
    target_link_libraries(octobeat PRIVATE
        Qt6::Widgets
        Qt6::Svg
        Qt6::Network
        Qt6::Concurrent
        octobeat_core
        octobeat_audio
        ole32
        winmm
        avrt
        ksuser
        ws2_32
        advapi32
        userenv
        # Required by the Rust standard library and windows-core:
        # WaitOnAddress/WakeByAddress, Nt* file APIs, PropVariant and WinRT.
        synchronization
        ntdll
        propsys
        runtimeobject
        oleaut32
        bcrypt
    )
else()
    target_link_libraries(octobeat PRIVATE
        Qt6::Widgets
        Qt6::Svg
        Qt6::Network
        Qt6::Concurrent
        octobeat_core
        octobeat_audio
    )
endif()

set_target_properties(octobeat PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)


install(TARGETS octobeat RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../themes"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/octobeat)
install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../icons"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/octobeat)
install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../resources"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/octobeat)
install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../assets"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/octobeat OPTIONAL)
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/../packaging/linux/io.github.ukimaka.OctoBeat.desktop"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/applications)
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/../packaging/linux/io.github.ukimaka.OctoBeat.metainfo.xml"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/metainfo)
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/../icons/octobeat  exe installer.svg"
        DESTINATION ${CMAKE_INSTALL_DATADIR}/icons/hicolor/scalable/apps
        RENAME io.github.ukimaka.OctoBeat.svg)
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../packaging/tools/runtime")
    install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../packaging/tools/runtime/"
            DESTINATION ${CMAKE_INSTALL_DATADIR}/octobeat/tools
            USE_SOURCE_PERMISSIONS)
endif()

set(CPACK_PACKAGE_NAME "OctoBeat")
set(CPACK_PACKAGE_VENDOR "ukimaka")
set(CPACK_PACKAGE_VERSION ${PROJECT_VERSION})
set(CPACK_PACKAGE_CONTACT "ukimaka")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "OctoBeat music player")
set(CPACK_GENERATOR "TGZ")
set(CPACK_PACKAGE_FILE_NAME "OctoBeat-${PROJECT_VERSION}-Linux-${CMAKE_SYSTEM_PROCESSOR}")
set(CPACK_INCLUDE_TOPLEVEL_DIRECTORY ON)
include(CPack)
