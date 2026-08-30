import Foundation
import XCTest
@testable import MacflowCore

final class LayoutPlanTests: XCTestCase {
    private let screen = Frame(x: 0, y: 25, width: 1680, height: 1025)

    func testColumnsSetFramesRaiseNonfocusApplicationAndFocusLast() throws {
        let layout = WorkflowConfiguration.Layout(
            type: .columns,
            applications: ["first", "second"],
            ratios: [0.5, 0.5],
            targetScreenApplication: "first",
            focus: "first",
            gap: 8
        )

        let plan = try LayoutPlanner.plan(layout: layout, screen: screen)

        XCTAssertEqual(plan.operations, [
            .setFrame(application: "first", frame: Frame(x: 0, y: 25, width: 836, height: 1025)),
            .setFrame(application: "second", frame: Frame(x: 844, y: 25, width: 836, height: 1025)),
            .raise(application: "second"),
            .wait(seconds: LayoutPlanner.activationSettleSeconds),
            .focus(application: "first"),
        ])
    }

    func testReversedColumnsFollowConfiguredOrderAndFocus() throws {
        let layout = WorkflowConfiguration.Layout(
            type: .columns,
            applications: ["second", "first"],
            ratios: [0.5, 0.5],
            focus: "second",
            gap: 8
        )

        let plan = try LayoutPlanner.plan(layout: layout, screen: screen)

        XCTAssertEqual(plan.operations, [
            .setFrame(application: "second", frame: Frame(x: 0, y: 25, width: 836, height: 1025)),
            .setFrame(application: "first", frame: Frame(x: 844, y: 25, width: 836, height: 1025)),
            .raise(application: "first"),
            .wait(seconds: LayoutPlanner.activationSettleSeconds),
            .focus(application: "second"),
        ])
        XCTAssertFalse(encodedApplications(in: plan).contains("unrelated"))
    }

    func testMaximizeSetsFrameThenFocusesConfiguredApplication() throws {
        let layout = WorkflowConfiguration.Layout(
            type: .maximize,
            applications: ["first"],
            focus: "first"
        )

        XCTAssertEqual(try LayoutPlanner.plan(layout: layout, screen: screen).operations, [
            .setFrame(application: "first", frame: screen),
            .focus(application: "first"),
        ])
    }

    func testPlanRejectsFocusOutsideLayoutParticipants() {
        let layout = WorkflowConfiguration.Layout(
            type: .columns,
            applications: ["first", "second"],
            ratios: [0.5, 0.5],
            focus: "unrelated",
            gap: 8
        )

        XCTAssertThrowsError(try LayoutPlanner.plan(layout: layout, screen: screen)) { error in
            XCTAssertEqual(error as? LayoutPlanningError, .focusNotInLayout("unrelated"))
        }
    }

    func testEachNonfocusApplicationSettlesBeforeTheNextOperation() throws {
        let layout = WorkflowConfiguration.Layout(
            type: .columns,
            applications: ["first", "second", "third"],
            ratios: [1, 1, 1],
            focus: "third",
            gap: 0
        )

        let plan = try LayoutPlanner.plan(
            layout: layout,
            screen: Frame(x: 0, y: 0, width: 1200, height: 800)
        )

        XCTAssertEqual(Array(plan.operations.suffix(5)), [
            .raise(application: "first"),
            .wait(seconds: LayoutPlanner.activationSettleSeconds),
            .raise(application: "second"),
            .wait(seconds: LayoutPlanner.activationSettleSeconds),
            .focus(application: "third"),
        ])
    }

    func testPlanSerializesToApplicationNeutralOperations() throws {
        let plan = LayoutPlan(operations: [
            .setFrame(application: "first", frame: Frame(x: 0, y: 25, width: 836, height: 1025)),
            .raise(application: "second"),
            .wait(seconds: 0.2),
            .focus(application: "first"),
        ])

        let data = try JSONEncoder().encode(plan)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let operations = try XCTUnwrap(object["operations"] as? [[String: Any]])
        XCTAssertEqual(operations.map { $0["type"] as? String }, ["set_frame", "raise", "wait", "focus"])
        XCTAssertEqual(operations.compactMap { $0["application"] as? String }, ["first", "second", "first"])
        XCTAssertEqual(operations[2]["seconds"] as? Double, 0.2)
        XCTAssertEqual(try JSONDecoder().decode(LayoutPlan.self, from: data), plan)
    }

    private func encodedApplications(in plan: LayoutPlan) -> [String] {
        plan.operations.map { operation in
            switch operation {
            case let .setFrame(application, _), let .raise(application), let .focus(application):
                return application
            case .wait:
                return ""
            }
        }.filter { !$0.isEmpty }
    }
}
