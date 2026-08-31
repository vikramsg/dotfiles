import Foundation
import XCTest
@testable import MacflowUI

final class FileDragGestureTests: XCTestCase {
    private let first = URL(fileURLWithPath: "/first.png")
    private let second = URL(fileURLWithPath: "/second.png")

    func testQuickDragStartsWhenPreparationCompletes() {
        var gesture = FileDragGesture<String>()
        gesture.mouseDown()

        XCTAssertNil(gesture.mouseDragged("drag-event"))
        let drag = gesture.prepare(first)

        XCTAssertEqual(drag?.0, first)
        XCTAssertEqual(drag?.1, "drag-event")
    }

    func testPreparationAfterMouseUpCannotArmLaterDrag() {
        var gesture = FileDragGesture<String>()
        gesture.mouseDown()
        gesture.mouseUp()

        XCTAssertNil(gesture.prepare(first))
        gesture.mouseDown()
        XCTAssertNil(gesture.mouseDragged("later-drag"))
    }

    func testCurrentPressCannotDragPreviouslyPreparedFile() {
        var gesture = FileDragGesture<String>()
        gesture.mouseDown()
        XCTAssertNil(gesture.prepare(first))
        gesture.mouseUp()

        gesture.mouseDown()
        XCTAssertNil(gesture.prepare(second))
        let drag = gesture.mouseDragged("current-drag")

        XCTAssertEqual(drag?.0, second)
        XCTAssertEqual(drag?.1, "current-drag")
    }
}
