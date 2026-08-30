import Foundation

public struct Frame: Codable, Equatable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }
}

public enum LayoutGeometry {
    public static func maximize(in screen: Frame) -> Frame {
        screen
    }

    public static func columns(in screen: Frame, ratios: [Double], gap: Double) -> [Frame] {
        guard !ratios.isEmpty else { return [] }
        let total = ratios.reduce(0, +)
        guard total > 0 else { return [] }

        let usableWidth = max(0, screen.width - gap * Double(ratios.count - 1))
        var x = screen.x
        return ratios.map { ratio in
            let width = usableWidth * ratio / total
            defer { x += width + gap }
            return Frame(x: x, y: screen.y, width: width, height: screen.height)
        }
    }
}
