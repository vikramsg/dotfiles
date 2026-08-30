import XCTest
@testable import MacflowCore

final class GeometryTests: XCTestCase {
    func testExactHalfSplitWithoutGap() {
        let frames = LayoutGeometry.columns(
            in: Frame(x: 0, y: 25, width: 1200, height: 800),
            ratios: [0.5, 0.5],
            gap: 0
        )
        XCTAssertEqual(frames, [
            Frame(x: 0, y: 25, width: 600, height: 800),
            Frame(x: 600, y: 25, width: 600, height: 800),
        ])
    }

    func testSplitSubtractsOneInnerGap() {
        let frames = LayoutGeometry.columns(
            in: Frame(x: 100, y: 20, width: 1000, height: 700),
            ratios: [0.65, 0.35],
            gap: 10
        )
        XCTAssertEqual(frames[0].width, 643.5)
        XCTAssertEqual(frames[1].x, 753.5)
        XCTAssertEqual(frames[1].width, 346.5)
    }
}
