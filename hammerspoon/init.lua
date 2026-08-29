require("hs.ipc")

local FlowVisionShelf = require("flowvision_shelf")

hs.autoLaunch(true)

FlowVisionShelfInstance = FlowVisionShelf.start({
    folder = "/Users/Shared/Screenshots",
    modifiers = { "cmd", "shift" },
    key = "h",
    closeDelay = 0.2,
})
