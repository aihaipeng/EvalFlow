# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

EvalFlow is used by a small internal team of approximately four to five Agent and test engineers. Each user runs the application independently on their own computer through localhost to manage test data, configure workflows, and execute or trace batch Runs.

## Product Purpose

EvalFlow is a local enterprise Agent testing and orchestration tool. It enables users to manage database-backed test sets, maintain model suppliers and restricted visual workflows, create batch Runs, execute cases concurrently, resume interrupted work, and trace execution results.

Success means users can maintain and execute test cases efficiently without editing or coordinating shared Excel files, while each Run remains reproducible and traceable.

## Positioning

The product combines editable database-backed test sets, constrained visual workflow configuration, and immutable Run-local snapshots of test-set cases and workflow structure. A Run is isolated from later edits to its source test set or workflow.

## Operating Context

- Each user runs the application independently through localhost.
- Test cases are imported from local `.xlsx` files only as browser-side source material and then stored in the database.
- Excel is not a workflow runtime dependency and is not uploaded.
- Users create and maintain test sets, configure model suppliers and workflows, then create and operate batch Runs.
- Runs support concurrent case execution, interruption recovery, and execution tracing.

## Capabilities and Constraints

- Test sets support database-backed creation, editing, deletion, field management, and case management.
- Test-set fields are workflow keys and default to `col_1`, `col_2`, and so on.
- Run creation selects an existing test set and workflow.
- Run creation freezes immutable test-set and workflow snapshots.
- The application is designed for local desktop browser use.
- The current frontend optimization must not alter APIs, database structures, business behavior, or Workflow canvas interactions.
- Historical Excel-backed Runs are not migrated.

## Brand Commitments

- Product name: EvalFlow.
- Chinese is the primary interface language.
- Existing business terminology such as 测试集、供应商、工作流、任务调度 and Run should remain consistent.

## Evidence on Hand

- Existing functional frontend and backend implementation in this repository.
- Real local test sets and workflow data are available through the running localhost application.
- No testimonials, customer claims, benchmark claims, or marketing proof should be invented.

## Product Principles

1. Preserve reproducibility by freezing Run-local inputs and workflow structure.
2. Keep routine testing operations fast, direct, and locally controlled.
3. Make management interfaces consistent and easy to scan.
4. Remove runtime dependence on mutable Excel files.
5. Improve visual quality without changing confirmed business behavior.
