import os
import gc
import streamlit as st
import psutil

def is_admin_mode():
    return st.session_state.get('admin_mode', False)

def force_garbage_collection():
    collected = gc.collect()
    if is_admin_mode():
        st.info(f"🧹 강제 메모리 정리 완료! 수집된 객체 수: {collected}")
    return collected

class MemoryManager:
    def __enter__(self):
        self.initial_memory = self.get_memory_usage()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        collected = gc.collect()
        if is_admin_mode():
            final_memory = self.get_memory_usage()
            memory_freed = self.initial_memory - final_memory
            st.info(f"🧹 메모리 정리 완료! 해제된 메모리: {memory_freed:.2f} MB, 수집된 객체: {collected}")
            
            if exc_type:
                st.warning(f"⚠️ 예외 발생: {exc_type.__name__}: {exc_val}")

    def get_memory_usage(self):
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
