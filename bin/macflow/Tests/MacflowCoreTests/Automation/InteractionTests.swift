import XCTest
@testable import MacflowCore

final class InteractionTests: XCTestCase {
    func testKnownKeysResolveAndUnknownKeysDoNot() {
        XCTAssertEqual(KeyCodeResolver.resolve("g"), 5)
        XCTAssertEqual(KeyCodeResolver.resolve("escape"), 53)
        XCTAssertNil(KeyCodeResolver.resolve("not-a-key"))
    }

    func testDragDurationBoundaries() throws {
        XCTAssertEqual(try InputValidation.dragDelayMicroseconds(duration: 60, steps: 20), 3_000_000)
        XCTAssertThrowsError(try InputValidation.dragDelayMicroseconds(duration: 60.001, steps: 20))
        XCTAssertThrowsError(try InputValidation.dragDelayMicroseconds(duration: -.infinity, steps: 20))
    }

    func testOverlappingSuspensionsRemainSuspendedUntilAllResume() {
        var gate = SuspensionGate()
        gate.suspend()
        gate.suspend()
        gate.resume()
        XCTAssertTrue(gate.isSuspended)
        gate.resume()
        XCTAssertFalse(gate.isSuspended)
    }

    func testGlobalShortcutConsumesOnePressAndPassesAfterRemoval() throws {
        let chord = try XCTUnwrap(HotKeyChord(modifiers: ["cmd", "shift"], key: "3"))
        var router = GlobalHotKeyRouter()
        XCTAssertTrue(router.register(chord, bindingID: 7))

        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift])),
            HotKeyDecision(consume: true, triggeredBindingID: 7)
        )
        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [], isRepeat: true)),
            HotKeyDecision(consume: true, triggeredBindingID: nil)
        )
        XCTAssertEqual(
            router.handle(keyEvent(.keyUp, key: "3", modifiers: [.command, .shift])),
            HotKeyDecision(consume: true, triggeredBindingID: nil)
        )

        router.unregister(bindingID: 7)
        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift])),
            HotKeyDecision(consume: false, triggeredBindingID: nil)
        )
    }

    func testGlobalShortcutPassesUnconfiguredAndNonExactChords() throws {
        let chord = try XCTUnwrap(HotKeyChord(modifiers: ["cmd", "shift"], key: "3"))
        var router = GlobalHotKeyRouter()
        XCTAssertTrue(router.register(chord, bindingID: 7))

        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "9", modifiers: [.command, .shift])),
            HotKeyDecision(consume: false, triggeredBindingID: nil)
        )
        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift, .option])),
            HotKeyDecision(consume: false, triggeredBindingID: nil)
        )
    }

    func testGlobalShortcutCanTriggerAgainAfterPressStateReset() throws {
        let chord = try XCTUnwrap(HotKeyChord(modifiers: ["cmd", "shift"], key: "3"))
        var router = GlobalHotKeyRouter()
        XCTAssertTrue(router.register(chord, bindingID: 7))

        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift])),
            HotKeyDecision(consume: true, triggeredBindingID: 7)
        )
        router.resetPressState()
        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift])),
            HotKeyDecision(consume: true, triggeredBindingID: 7)
        )
    }

    func testTemporaryBindingTakesPrecedenceUntilRemoved() throws {
        let escape = try XCTUnwrap(HotKeyChord(modifiers: [], key: "escape"))
        var router = GlobalHotKeyRouter()
        XCTAssertTrue(router.register(escape, bindingID: 1))
        XCTAssertTrue(router.register(escape, bindingID: 2))

        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "escape", modifiers: [])),
            HotKeyDecision(consume: true, triggeredBindingID: 2)
        )
        _ = router.handle(keyEvent(.keyUp, key: "escape", modifiers: []))
        router.unregister(bindingID: 2)
        XCTAssertEqual(
            router.handle(keyEvent(.keyDown, key: "escape", modifiers: [])),
            HotKeyDecision(consume: true, triggeredBindingID: 1)
        )
    }

    private func keyEvent(
        _ phase: HotKeyEventPhase,
        key: String,
        modifiers: Set<HotKeyModifier>,
        isRepeat: Bool = false
    ) -> HotKeyInputEvent {
        HotKeyInputEvent(
            phase: phase,
            keyCode: KeyCodeResolver.resolve(key)!,
            modifiers: modifiers,
            isRepeat: isRepeat
        )
    }
}
