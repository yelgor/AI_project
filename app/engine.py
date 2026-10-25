"""Own each upstream native/JIT scene in a fresh process; exchange plain data."""
import multiprocessing
import os
import threading


def _serve(connection, config, parent_pid):
    # A killed host must not leave a CPU worker running outside Docker either.
    import ctypes
    import signal
    ctypes.CDLL(None).prctl(1,signal.SIGTERM)
    if os.getppid()!=parent_pid:return
    model=None
    try:
        try:
            from .radio import Radio
        except ImportError:
            from radio import Radio
        model=Radio(config);connection.send(('ok',None))
        while True:
            command,data=connection.recv()
            if command=='close':break
            try:
                if command!='sample':raise ValueError('Unknown solver command')
                connection.send(('ok',model.sample(*data)))
            except ValueError as error:connection.send(('validation',str(error)))
            except Exception as error:connection.send(('error',f'{type(error).__name__}: {error}'))
    except EOFError:pass
    except Exception as error:
        try:connection.send(('error',f'{type(error).__name__}: {error}'))
        except (BrokenPipeError,OSError):pass
    finally:
        if model:model.close()
        connection.close()


class RadioWorker:
    """Same sample interface; a native crash cannot terminate the HTTP backend."""
    def __init__(self,config):
        self.lock=threading.RLock();self.closed=False
        context=multiprocessing.get_context('spawn')
        self.connection,child=context.Pipe()
        self.process=context.Process(target=_serve,args=(child,config,os.getpid()),daemon=True)
        self.process.start();child.close()
        try:self.receive()
        except BaseException:self.close();raise

    def receive(self,timeout=120):
        try:
            if not self.connection.poll(timeout):
                self.process.terminate();self.process.join(timeout=5)
                raise RuntimeError('Sionna worker timed out; apply the scene again to restart it')
            kind,value=self.connection.recv()
        except (EOFError,OSError) as error:
            self.process.join(timeout=1)
            raise RuntimeError(f'Sionna worker exited (code {self.process.exitcode}); apply the scene again') from error
        if kind=='validation':raise ValueError(value)
        if kind!='ok':raise RuntimeError('Sionna worker: '+str(value))
        return value

    def sample(self,position,orientation=None,include_paths=True):
        with self.lock:
            if self.closed or not self.process.is_alive():raise RuntimeError('Sionna worker is not running; reapply scene')
            try:self.connection.send(('sample',(position,orientation,include_paths)))
            except (BrokenPipeError,OSError) as error:raise RuntimeError('Sionna worker connection closed') from error
            return self.receive()

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True
            if self.process.is_alive():
                try:self.connection.send(('close',None))
                except (BrokenPipeError,OSError):pass
                self.process.join(timeout=3)
                if self.process.is_alive():self.process.terminate();self.process.join(timeout=3)
                if self.process.is_alive():self.process.kill();self.process.join(timeout=3)
            else:self.process.join(timeout=1)
            self.connection.close()

    def __del__(self):
        try:self.close()
        except Exception:pass
