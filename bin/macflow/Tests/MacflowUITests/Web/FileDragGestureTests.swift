import Foundation
import Testing
@testable import MacflowUI

@Suite
struct FileDragGestureTests {
    private let first = URL(fileURLWithPath: "/first.png")
    private let second = URL(fileURLWithPath: "/second.png")

    @Test
    func quickDragStartsWhenPreparationCompletes() {
        var gesture = FileDragGesture<String>()
        gesture.mouseDown()

        #expect(gesture.mouseDragged("drag-event") == nil)
        let drag = gesture.prepare(first)

        #expect(drag?.0 == first)
        #expect(drag?.1 == "drag-event")
    }

    @Test
    func preparationAfterMouseUpCannotArmLaterDrag() {
        var gesture = FileDragGesture<String>()
        gesture.mouseDown()
        gesture.mouseUp()

        #expect(gesture.prepare(first) == nil)
        gesture.mouseDown()
        #expect(gesture.mouseDragged("later-drag") == nil)
    }

    @Test
    func currentPressCannotDragPreviouslyPreparedFile() {
        var gesture = FileDragGesture<String>()
        gesture.mouseDown()
        #expect(gesture.prepare(first) == nil)
        gesture.mouseUp()

        gesture.mouseDown()
        #expect(gesture.prepare(second) == nil)
        let drag = gesture.mouseDragged("current-drag")

        #expect(drag?.0 == second)
        #expect(drag?.1 == "current-drag")
    }
}
