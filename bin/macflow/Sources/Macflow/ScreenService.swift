import AppKit
import CoreGraphics
import MacflowCore

struct ScreenRecord {
    let id: CGDirectDisplayID
    let name: String
    let frame: CGRect
    let visibleFrame: CGRect
    let main: Bool

    var json: [String: Any] {
        [
            "id": id,
            "name": name,
            "main": main,
            "frame": frame.dictionary,
            "visible_frame": visibleFrame.dictionary,
        ]
    }
}

extension CGRect {
    var dictionary: [String: Double] {
        ["x": origin.x, "y": origin.y, "width": width, "height": height]
    }

    var workflowFrame: Frame {
        Frame(x: origin.x, y: origin.y, width: width, height: height)
    }
}

final class ScreenService {
    func all() -> [ScreenRecord] {
        let primaryHeight = NSScreen.screens.first(where: { $0.frame.origin == .zero })?.frame.height
            ?? NSScreen.main?.frame.height
            ?? 0
        return NSScreen.screens.compactMap { screen in
            guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
                return nil
            }
            let id = CGDirectDisplayID(number.uint32Value)
            let visible = screen.visibleFrame
            let accessibilityFrame = CGRect(
                x: visible.minX,
                y: primaryHeight - visible.maxY,
                width: visible.width,
                height: visible.height
            )
            return ScreenRecord(
                id: id,
                name: screen.localizedName,
                frame: CGDisplayBounds(id),
                visibleFrame: accessibilityFrame,
                main: CGDisplayIsMain(id) != 0
            )
        }
    }

    func containing(_ frame: CGRect) -> ScreenRecord? {
        let point = CGPoint(x: frame.midX, y: frame.midY)
        return all().first { $0.frame.contains(point) } ?? all().first(where: \.main)
    }
}
