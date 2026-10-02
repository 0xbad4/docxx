#include "testlib/core.h"

namespace testlib {

Widget::Widget(std::string name) : name_(std::move(name)) {}

Widget::~Widget() = default;

/**
 * @param buffer additional detail added at the definition site.
 * @return -2 if the buffer was null (implementation detail).
 */
int Widget::render(char* buffer, int max_len) const {
    if (!buffer) return -2;
    return 0;
}

const char* err_str(error_type e) {
    switch (e) {
        case error_type::NONE: return "none";
        default: return "unknown";
    }
}

bool run(const std::vector<Widget>& widgets, error_type* error) {
    (void)widgets;
    if (error) *error = error_type::NONE;
    return true;
}

// purely internal, undocumented, .cpp-only helper -> should not appear in docs
static int internal_counter(){ return 42; }

namespace detail {
void secret_helper() {
    internal_counter();
}
}

} // namespace testlib
