/********************************************************************************
 * Copyright (c) 2025 Contributors to the Eclipse Foundation
 *
 * See the NOTICE file(s) distributed with this work for additional
 * information regarding copyright ownership.
 *
 * This program and the accompanying materials are made available under the
 * terms of the Apache License Version 2.0 which is available at
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * SPDX-License-Identifier: Apache-2.0
 ********************************************************************************/
#ifndef SCORE_MW_COM_IMPL_METHODS_METHOD_SIGNATURE_ELEMENT_PTR_H
#define SCORE_MW_COM_IMPL_METHODS_METHOD_SIGNATURE_ELEMENT_PTR_H

#include <cstddef>

namespace score::mw::com::impl
{
/// \brief Tag type to indicate a pointer to a method signature element (argument or return type).
template <typename SignatureElement>
class MethodSignatureElementPtr
{
  public:
    /// \brief Constructor
    /// \param element reference to the method signature element.
    /// \param ptr_active bool reference indicating, if the pointer is active. Will be set to true in ctor and set to
    /// false in dtor.
    /// \param queue_pos in which call-queue position this pointer is used.
    explicit MethodSignatureElementPtr(SignatureElement& element, bool& ptr_active, std::size_t queue_pos)
        : element_ptr_(&element), ptr_active_(ptr_active), queue_position_(queue_pos)
    {
        ptr_active_ = true;
    }

    MethodSignatureElementPtr(const MethodSignatureElementPtr&) = delete;
    MethodSignatureElementPtr& operator=(const MethodSignatureElementPtr&) = delete;

    /// \brief Move constructor
    /// \param other rvalue reference to another MethodSignatureElementPtr to move from.
    /// \details  The moved-from instance will have its internal pointer set to nullptr, which signals, that it is no
    /// longer owning the ptr_active_ flag.
    MethodSignatureElementPtr(MethodSignatureElementPtr&& other) noexcept
        : element_ptr_(other.element_ptr_), ptr_active_(other.ptr_active_), queue_position_(other.queue_position_)
    {
        other.element_ptr_ = nullptr;
    };

    /// \brief Move assignment operator deleted as we don't see a use case for it yet. If we would implement it, we
    /// would have to take care of the ptr_active_ flag of the current instance first!
    MethodSignatureElementPtr& operator=(MethodSignatureElementPtr&& other) noexcept = delete;

    ~MethodSignatureElementPtr()
    {
        if (element_ptr_ != nullptr)
        {
            ptr_active_ = false;
        }
    }

    /// \brief Returns the raw pointer to the method signature element.
    /// \return raw pointer to the method signature element.
    SignatureElement* get() const noexcept
    {
        return element_ptr_;
    }

    SignatureElement* operator->() const noexcept
    {
        return get();
    }

    SignatureElement& operator*() const noexcept
    {
        return *element_ptr_;
    }

    std::size_t GetQueuePosition() const noexcept // test
    {
        return queue_position_;
    }

  private:
    SignatureElement* element_ptr_;
    bool& ptr_active_;
    std::size_t queue_position_;
};

template <typename Type>
using MethodInArgPtr = MethodSignatureElementPtr<Type>;

template <typename Type>
using MethodReturnTypePtr = MethodSignatureElementPtr<Type>;

}  // namespace score::mw::com::impl

#endif  // SCORE_MW_COM_IMPL_METHODS_METHOD_SIGNATURE_ELEMENT_PTR_H
