import Testing
@testable import MacflowCore

@Suite struct InteractionTests {
    @Test func testKnownKeysResolveAndUnknownKeysDoNot() {
        #expect(KeyCodeResolver.resolve("g") == 5)
        #expect(KeyCodeResolver.resolve("escape") == 53)
        #expect(KeyCodeResolver.resolve("not-a-key") == nil)
    }

    @Test func testDragDurationBoundaries() throws {
        #expect(try InputValidation.dragDelayMicroseconds(duration: 60, steps: 20) == 3_000_000)
        #expect(throws: Error.self) {
            try InputValidation.dragDelayMicroseconds(duration: 60.001, steps: 20)
        }
        #expect(throws: Error.self) {
            try InputValidation.dragDelayMicroseconds(duration: -.infinity, steps: 20)
        }
    }

    @Test func testOverlappingSuspensionsRemainSuspendedUntilAllResume() {
        var gate = SuspensionGate()
        gate.suspend()
        gate.suspend()
        gate.resume()
        #expect(gate.isSuspended)
        gate.resume()
        #expect(!gate.isSuspended)
    }

    @Test func testGlobalShortcutConsumesOnePressAndPassesAfterRemoval() throws {
        let chord = try #require(HotKeyChord(modifiers: ["cmd", "shift"], key: "3"))
        var router = GlobalHotKeyRouter()
        let registered = router.register(chord, bindingID: 7)
        #expect(registered)

        #expect(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift]))
                == HotKeyDecision(consume: true, triggeredBindingID: 7)
        )
        #expect(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [], isRepeat: true))
                == HotKeyDecision(consume: true, triggeredBindingID: nil)
        )
        #expect(
            router.handle(keyEvent(.keyUp, key: "3", modifiers: [.command, .shift]))
                == HotKeyDecision(consume: true, triggeredBindingID: nil)
        )

        router.unregister(bindingID: 7)
        #expect(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift]))
                == HotKeyDecision(consume: false, triggeredBindingID: nil)
        )
    }

    @Test func testGlobalShortcutPassesUnconfiguredAndNonExactChords() throws {
        let chord = try #require(HotKeyChord(modifiers: ["cmd", "shift"], key: "3"))
        var router = GlobalHotKeyRouter()
        let registered = router.register(chord, bindingID: 7)
        #expect(registered)

        #expect(
            router.handle(keyEvent(.keyDown, key: "9", modifiers: [.command, .shift]))
                == HotKeyDecision(consume: false, triggeredBindingID: nil)
        )
        #expect(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift, .option]))
                == HotKeyDecision(consume: false, triggeredBindingID: nil)
        )
    }

    @Test func testGlobalShortcutCanTriggerAgainAfterPressStateReset() throws {
        let chord = try #require(HotKeyChord(modifiers: ["cmd", "shift"], key: "3"))
        var router = GlobalHotKeyRouter()
        let registered = router.register(chord, bindingID: 7)
        #expect(registered)

        #expect(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift]))
                == HotKeyDecision(consume: true, triggeredBindingID: 7)
        )
        router.resetPressState()
        #expect(
            router.handle(keyEvent(.keyDown, key: "3", modifiers: [.command, .shift]))
                == HotKeyDecision(consume: true, triggeredBindingID: 7)
        )
    }

    @Test func testTemporaryBindingTakesPrecedenceUntilRemoved() throws {
        let escape = try #require(HotKeyChord(modifiers: [], key: "escape"))
        var router = GlobalHotKeyRouter()
        let registeredPrimary = router.register(escape, bindingID: 1)
        let registeredTemporary = router.register(escape, bindingID: 2)
        #expect(registeredPrimary)
        #expect(registeredTemporary)

        #expect(
            router.handle(keyEvent(.keyDown, key: "escape", modifiers: []))
                == HotKeyDecision(consume: true, triggeredBindingID: 2)
        )
        _ = router.handle(keyEvent(.keyUp, key: "escape", modifiers: []))
        router.unregister(bindingID: 2)
        #expect(
            router.handle(keyEvent(.keyDown, key: "escape", modifiers: []))
                == HotKeyDecision(consume: true, triggeredBindingID: 1)
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
