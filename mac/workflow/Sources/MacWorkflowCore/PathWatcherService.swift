import Darwin
import Foundation

public final class PathWatcherService {
    private let directory: URL
    private let debounceSeconds: Double
    private let callback: () -> Void
    private let queue: DispatchQueue
    private var source: DispatchSourceFileSystemObject?
    private var descriptor: Int32 = -1
    private var pending: DispatchWorkItem?

    public init(
        directory: URL,
        debounceSeconds: Double,
        queue: DispatchQueue = .main,
        callback: @escaping () -> Void
    ) {
        self.directory = directory
        self.debounceSeconds = debounceSeconds
        self.queue = queue
        self.callback = callback
    }

    public func start() throws {
        stop()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        descriptor = open(directory.path, O_EVTONLY)
        guard descriptor >= 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .rename, .delete],
            queue: queue
        )
        source.setEventHandler { [weak self] in
            guard let self, let source = self.source else { return }
            let events = source.data
            if events.contains(.rename) || events.contains(.delete) {
                self.reopen()
            } else {
                self.schedule()
            }
        }
        source.setCancelHandler { [descriptor] in close(descriptor) }
        self.source = source
        source.resume()
    }

    public func stop() {
        pending?.cancel()
        pending = nil
        source?.cancel()
        source = nil
        descriptor = -1
    }

    public func schedule(delay: Double? = nil) {
        pending?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.callback() }
        pending = work
        queue.asyncAfter(deadline: .now() + (delay ?? debounceSeconds), execute: work)
    }

    private func reopen() {
        stop()
        queue.asyncAfter(deadline: .now() + debounceSeconds) { [weak self] in
            guard let self else { return }
            do {
                try self.start()
                self.callback()
            } catch {
                self.scheduleReopen()
            }
        }
    }

    private func scheduleReopen() {
        queue.asyncAfter(deadline: .now() + debounceSeconds) { [weak self] in
            guard let self else { return }
            do {
                try self.start()
                self.callback()
            } catch {
                self.scheduleReopen()
            }
        }
    }

    deinit { stop() }
}
