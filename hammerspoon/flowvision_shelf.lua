local M = {}

local DRAG_THRESHOLD = 8

function M.newDragTracker(threshold)
    local tracker = {
        threshold = threshold or DRAG_THRESHOLD,
        active = false,
        dragged = false,
        startX = 0,
        startY = 0,
    }

    function tracker:press(insideWindow, x, y)
        self.active = insideWindow
        self.dragged = false
        self.startX = x
        self.startY = y
    end

    function tracker:move(x, y)
        if not self.active then
            return
        end
        local dx = x - self.startX
        local dy = y - self.startY
        self.dragged = self.dragged or math.sqrt(dx * dx + dy * dy) >= self.threshold
    end

    function tracker:release(x, y)
        if self.active and x ~= nil and y ~= nil then
            self:move(x, y)
        end
        local completedDrag = self.active and self.dragged
        self.active = false
        self.dragged = false
        return completedDrag
    end

    return tracker
end

function M.pointInFrame(frame, point)
    return frame ~= nil
        and point.x >= frame.x
        and point.x <= frame.x + frame.w
        and point.y >= frame.y
        and point.y <= frame.y + frame.h
end

function M.folderURL(folder)
    return "file://" .. folder:gsub("([^%w%-._~/])", function(character)
        return string.format("%%%02X", string.byte(character))
    end)
end

function M.pinMenuPath()
    return { "View", "Keep Current Window on Top" }
end

function M.windowFrame(screenFrame, width, height)
    local resolvedWidth = math.min(width, screenFrame.w - 40)
    local resolvedHeight = math.min(height, screenFrame.h - 40)
    return {
        x = screenFrame.x + (screenFrame.w - resolvedWidth) / 2,
        y = screenFrame.y + 20,
        w = resolvedWidth,
        h = resolvedHeight,
    }
end

local Shelf = {}
Shelf.__index = Shelf

function Shelf:_forgetWindow()
    if self.openTimer then
        self.openTimer:stop()
        self.openTimer = nil
    end
    if self.pinTimer then
        self.pinTimer:stop()
        self.pinTimer = nil
    end
    if self.escapeHotkey then
        self.escapeHotkey:disable()
    end
    if self.mouseTap then
        self.mouseTap:stop()
    end
    if self.closeTimer then
        self.closeTimer:stop()
        self.closeTimer = nil
    end
    self.dragTracker:release()
    self.windowID = nil
end

function Shelf:close()
    local window = self.windowID and self.hs.window.get(self.windowID) or nil
    self:_forgetWindow()
    if window then
        window:close()
    end
    local returnWindow = self.returnWindowID and self.hs.window.get(self.returnWindowID) or nil
    self.returnWindowID = nil
    if returnWindow then
        returnWindow:focus()
    end
end

function Shelf:_positionAndPin(window)
    window:setFrame(M.windowFrame(self.targetScreen:frame(), self.width, self.height))
    window:focus()

    local windowID = window:id()
    self.pinTimer = self.hs.timer.doAfter(0.2, function()
        self.pinTimer = nil
        if self.windowID ~= windowID then
            return
        end
        local application = window:application()
        local pinMenuPath = M.pinMenuPath()
        local pinItem = application and application:findMenuItem(pinMenuPath) or nil
        if pinItem and not pinItem.ticked then
            application:selectMenuItem(pinMenuPath)
        end
    end)
    self.escapeHotkey:enable()
    self.mouseTap:start()
end

function Shelf:_handleMouseEvent(event)
    local eventTypes = self.hs.eventtap.event.types
    local eventType = event:getType()
    local location = event:location()

    if eventType == eventTypes.leftMouseDown then
        local window = self.windowID and self.hs.window.get(self.windowID) or nil
        self.dragTracker:press(
            M.pointInFrame(window and window:frame() or nil, location),
            location.x,
            location.y
        )
    elseif eventType == eventTypes.leftMouseDragged then
        self.dragTracker:move(location.x, location.y)
    elseif eventType == eventTypes.leftMouseUp and self.dragTracker:release(location.x, location.y) then
        self.closeTimer = self.hs.timer.doAfter(self.closeDelay, function()
            self.closeTimer = nil
            self:close()
        end)
    end

    return false
end

function Shelf:_currentWindowIDs()
    local ids = {}
    for _, window in ipairs(self:_windows()) do
        ids[window:id()] = true
    end
    return ids
end

function Shelf:_windows()
    local application = self.hs.application.get("netdcy.FlowVision")
    return application and application:allWindows() or {}
end

function Shelf:_captureNewWindow(previousIDs)
    for _, window in ipairs(self:_windows()) do
        if not previousIDs[window:id()] then
            self.windowID = window:id()
            self:_positionAndPin(window)
            return true
        end
    end
    return false
end

function Shelf:show()
    if self.windowID then
        local existingWindow = self.hs.window.get(self.windowID)
        if existingWindow then
            existingWindow:unminimize()
            self:_positionAndPin(existingWindow)
            return
        end
        self:_forgetWindow()
    end

    local focusedWindow = self.hs.window.focusedWindow()
    self.returnWindowID = focusedWindow and focusedWindow:id() or nil
    self.targetScreen = self.hs.screen.mainScreen()
    local previousIDs = self:_currentWindowIDs()
    if not self.hs.urlevent.openURLWithBundle(M.folderURL(self.folder), "netdcy.FlowVision") then
        self.hs.alert.show("Could not open FlowVision screenshot shelf")
        return
    end

    local attempts = 0
    self.openTimer = self.hs.timer.waitUntil(function()
        attempts = attempts + 1
        return self:_captureNewWindow(previousIDs) or attempts >= 300
    end, function()
        self.openTimer = nil
        if not self.windowID then
            self.hs.alert.show("FlowVision did not open a screenshot window")
        end
    end, 0.05)
end

function M.start(options)
    local runtime = hs
    local shelf = setmetatable({
        hs = runtime,
        folder = assert(options.folder, "screenshot shelf folder is required"),
        width = options.width or 1200,
        height = options.height or 420,
        closeDelay = options.closeDelay or 0.5,
        dragTracker = M.newDragTracker(options.dragThreshold),
    }, Shelf)

    shelf.windowFilter = runtime.window.filter.new("FlowVision")
    shelf.mouseTap = runtime.eventtap.new({
        runtime.eventtap.event.types.leftMouseDown,
        runtime.eventtap.event.types.leftMouseDragged,
        runtime.eventtap.event.types.leftMouseUp,
    }, function(event)
        return shelf:_handleMouseEvent(event)
    end)
    shelf.escapeHotkey = runtime.hotkey.new({}, "escape", function()
        shelf:close()
    end)
    shelf.hotkey = runtime.hotkey.bind(options.modifiers, options.key, function()
        shelf:show()
    end)
    shelf.windowFilter:subscribe(runtime.window.filter.windowDestroyed, function(window)
        if window:id() == shelf.windowID then
            shelf:_forgetWindow()
        end
    end)
    return shelf
end

return M
