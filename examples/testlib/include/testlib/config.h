#pragma once
#include "testlib/core.h"

/**
 * @namespace testlib::cfg
 * @brief Configuration loading and validation.
 */
namespace testlib::cfg {

/**
 * @brief Load settings from a file.
 * @param path filesystem path to a config file
 * @throws std::runtime_error if the file cannot be parsed
 * @see save()
 */
bool load(const std::string& path);

/// Persists current settings back to @p path.
bool save(const std::string& path);

/// Global option: enables verbose logging.
extern bool verbose;

} // namespace testlib::cfg
