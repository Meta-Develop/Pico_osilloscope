cmake_minimum_required(VERSION 3.13)

if (NOT DEFINED PICO_BOARD)
	set(PICO_BOARD pico2 CACHE STRING "Target board")
endif()

set(PICO_NO_PICOTOOL 1 CACHE BOOL "Skip picotool dependency during local builds")

if (NOT PICO_SDK_PATH AND NOT DEFINED ENV{PICO_SDK_PATH})
	set(PICO_SDK_FETCH_FROM_GIT ON CACHE BOOL "Fetch Pico SDK automatically" FORCE)
	set(PICO_SDK_FETCH_FROM_GIT_PATH
		"${CMAKE_CURRENT_LIST_DIR}/build/_deps"
		CACHE PATH "Directory used to download the Pico SDK" FORCE)
endif()

include(pico_sdk_import.cmake)

project(pico_oscilloscope C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_subdirectory(src)
