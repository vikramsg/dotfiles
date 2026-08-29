package.path = "./?.lua;" .. package.path

local shelf = require("flowvision_shelf")

local function assertEqual(actual, expected, message)
    if actual ~= expected then
        error(string.format("%s: expected %s, got %s", message, tostring(expected), tostring(actual)))
    end
end

local tracker = shelf.newDragTracker(8)

tracker:press(false, 10, 10)
assertEqual(tracker:release(30, 30), false, "drag outside the shelf")

tracker:press(true, 10, 10)
assertEqual(tracker:release(14, 14), false, "movement below the threshold")

tracker:press(true, 10, 10)
assertEqual(tracker:release(18, 10), true, "release displacement at the threshold")
assertEqual(tracker:release(), false, "release resets drag state")

local bounds = { x = 100, y = 200, w = 500, h = 300 }
assertEqual(shelf.pointInFrame(bounds, { x = 100, y = 200 }), true, "top-left point")
assertEqual(shelf.pointInFrame(bounds, { x = 600, y = 500 }), true, "bottom-right point")
assertEqual(shelf.pointInFrame(bounds, { x = 99, y = 250 }), false, "outside point")

local arguments = shelf.openArguments("/Users/test/Screen Shots")
assertEqual(table.concat(arguments, "|"), "-g|-a|FlowVision|/Users/test/Screen Shots", "open arguments")

local frame = shelf.windowFrame({ x = 100, y = 200, w = 1400, h = 900 }, 1200, 420)
assertEqual(frame.x, 200, "centered x")
assertEqual(frame.y, 220, "top y")
assertEqual(frame.w, 1200, "width")
assertEqual(frame.h, 420, "height")

print("FlowVision shelf tests passed")
